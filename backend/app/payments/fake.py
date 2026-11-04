"""Pasarela simulada: desarrollo y tests de punta a punta. Nunca en produccion.

Con `PAYMENT_PROVIDER=fake` la pagina de pago es un formulario de la propia API
con dos botones, aprobar y rechazar (`api/v1/fake_checkout.py`), que anotan el
resultado aqui, en memoria. La aplicacion lo lee con `fetch_transaction`, igual
que reconsulta a una pasarela real: el resto del flujo es el de verdad, incluido
el enlace de un solo uso con el que el navegador abre la pagina.

Tambien guarda medios de pago y les cobra al instante: es la unica pasarela que
tokeniza, y con ella corren la renovacion automatica en desarrollo y sus tests.

No cobra nada.
"""

import json
import threading
import uuid
from collections.abc import Mapping
from html import escape

from app.payments.base import (
    CheckoutOrder,
    CheckoutPage,
    PaymentMethodOption,
    PaymentSource,
    PaymentSourceRejected,
    PaymentSourceType,
    ProviderEvent,
    ProviderTransaction,
    TokenizerInfo,
    TransactionStatus,
    unverified_event,
)

# Tokens que "devuelve" el selector simulado del frontend. El nombre dice que
# pasa despues: `-declined` guarda un medio cuyos cobros se rechazan, y
# `-rejected` es un medio que la pasarela ni siquiera acepta guardar.
FAKE_TOKEN_OK = "fake-token-ok"
FAKE_TOKEN_DECLINED = "fake-token-declined"
FAKE_TOKEN_REJECTED = "fake-token-rejected"

# Cabecera con la que un test marca un webhook simulado como autentico.
FAKE_SIGNATURE_HEADER = "x-fake-signature"
FAKE_SIGNATURE = "valida"

#: El catalogo simulado: un medio sin datos del comprador y uno que pide el
#: nombre, como los medios locales de Tipster Page, solo en Colombia.
FAKE_METHODS = (
    PaymentMethodOption(
        key="fakecard",
        name="Tarjeta simulada",
        logo_url=None,
        min_cents=100,
        max_cents=40_000,
        currency="EUR",
    ),
    PaymentMethodOption(
        key="fakelocal",
        name="Medio local simulado",
        logo_url=None,
        min_cents=100,
        max_cents=40_000,
        currency="EUR",
        countries=("CO",),
        fields=("firstName",),
    ),
)


class FakePaymentProvider:
    name = "fake"
    enabled = True
    lookup_by_reference = False

    def __init__(self, api_base_url: str = "http://localhost:8000") -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.transactions: dict[str, ProviderTransaction] = {}
        self._lock = threading.Lock()

    def describe(self) -> str:
        return "pasarela SIMULADA (PAYMENT_PROVIDER=fake): no cobra nada"

    def payment_methods(self, country: str | None) -> list[PaymentMethodOption]:
        return [m for m in FAKE_METHODS if not m.countries or (country in m.countries)]

    def start_checkout(self, order: CheckoutOrder) -> CheckoutPage:
        hidden = "".join(
            f'<input type="hidden" name="{name}" value="{escape(str(value), quote=True)}">'
            for name, value in (
                ("reference", order.reference),
                ("amount_cents", order.amount_cents),
                ("currency", order.currency),
                ("url_ok", order.url_ok),
                ("url_ko", order.url_ko),
            )
        )
        amount = f"{order.amount_cents // 100}.{order.amount_cents % 100:02d}"
        return CheckoutPage(
            html=f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Pasarela simulada</title></head>
<body style="font-family:sans-serif;max-width:32rem;margin:3rem auto;padding:0 1rem;">
<h1>Pasarela simulada</h1>
<p><strong>Solo desarrollo y pruebas. Aquí no se cobra nada.</strong></p>
<p>Referencia: {escape(order.reference)}<br>Medio: {escape(order.method)}<br>
Monto: {amount} {escape(order.currency)}</p>
<form method="post" action="{escape(self.api_base_url, quote=True)}/dev/fake-checkout">{hidden}
<button name="outcome" value="approved">Aprobar el pago</button>
<button name="outcome" value="declined">Rechazar el pago</button>
</form>
</body></html>"""
        )

    def resolve(
        self,
        *,
        reference: str,
        amount_cents: int,
        currency: str,
        status: TransactionStatus,
        status_message: str | None = None,
    ) -> ProviderTransaction:
        """Anota el resultado de una transaccion, como si el cliente hubiera pagado."""
        transaction = ProviderTransaction(
            id=f"fake-{uuid.uuid4().hex[:16]}",
            reference=reference,
            status=status,
            amount_cents=amount_cents,
            currency=currency,
            status_message=status_message,
        )
        with self._lock:
            self.transactions[transaction.id] = transaction
        return transaction

    def parse_event(self, body: bytes, headers: Mapping[str, str]) -> ProviderEvent:
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            payload = None
        if not isinstance(payload, dict):
            return unverified_event(self.name, body, None)
        signature = next(
            (v for k, v in headers.items() if k.lower() == FAKE_SIGNATURE_HEADER), None
        )
        event_id = payload.get("id")
        if signature != FAKE_SIGNATURE or not isinstance(event_id, str):
            return unverified_event(self.name, body, payload)
        transaction_id = payload.get("transaction_id")
        return ProviderEvent(
            event_id=f"{self.name}:{event_id}",
            event_type="transaction.updated",
            signature_verified=True,
            transaction_id=transaction_id if isinstance(transaction_id, str) else None,
            status=str(payload.get("status", "unknown")),
            payload=payload,
        )

    def fetch_transaction(self, transaction_id: str) -> ProviderTransaction | None:
        with self._lock:
            return self.transactions.get(transaction_id)

    def tokenizer(self) -> TokenizerInfo | None:
        return TokenizerInfo(kind="fake")

    def create_payment_source(
        self, *, source_type: PaymentSourceType, token: str, customer_email: str
    ) -> PaymentSource:
        if token not in (FAKE_TOKEN_OK, FAKE_TOKEN_DECLINED):
            raise PaymentSourceRejected("La pasarela simulada no acepta ese medio de pago")
        suffix = "ok" if token == FAKE_TOKEN_OK else "declined"
        return PaymentSource(
            id=f"fake-source-{suffix}-{uuid.uuid4().hex[:8]}",
            type=source_type,
            brand="VISA" if source_type == "CARD" else None,
            last4="4242" if source_type == "CARD" else None,
        )

    def charge(
        self,
        *,
        reference: str,
        amount_cents: int,
        currency: str,
        customer_email: str,
        source: PaymentSource,
    ) -> ProviderTransaction:
        """El cobro se resuelve al instante, segun el medio que se guardo."""
        approved = source.id.startswith("fake-source-ok-")
        return self.resolve(
            reference=reference,
            amount_cents=amount_cents,
            currency=currency,
            status="approved" if approved else "declined",
            status_message=None if approved else "Rechazado en la pasarela simulada",
        )
