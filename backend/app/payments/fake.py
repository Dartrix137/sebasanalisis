"""Pasarela simulada: desarrollo y tests de punta a punta. Nunca en produccion.

Con `PAYMENT_PROVIDER=fake` la pagina de pago es un formulario de la propia API
con dos botones, aprobar y rechazar (`api/v1/fake_checkout.py`), que anotan el
resultado aqui, en memoria. La aplicacion lo lee con `fetch_transaction`, igual
que reconsulta a una pasarela real: el resto del flujo es el de verdad, incluido
el enlace de un solo uso con el que el navegador abre la pagina.

Tambien tiene la renovacion automatica como Tipster Page (paso 5.3b): el alta
abre una pagina suya (`/dev/fake-checkout/subscription/:token`) donde se paga
el primer periodo y queda guardada una tarjeta simulada, y despues les cobra
al instante a las tarjetas guardadas. El cambio de tarjeta tambien tiene su
pagina (`/dev/fake-checkout/card/:token`).

No cobra nada.
"""

import json
import threading
import uuid
from collections.abc import Mapping
from html import escape

from app.payments.base import (
    ChargePeriod,
    CheckoutOrder,
    CheckoutPage,
    PaymentMethodOption,
    PaymentSource,
    PaymentSourceRejected,
    ProviderEvent,
    ProviderTransaction,
    RecurringOrder,
    RecurringStart,
    TransactionStatus,
    unverified_event,
)

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


#: El medio de la renovacion automatica simulada, en cualquier pais.
FAKE_RECURRING_METHOD = PaymentMethodOption(
    key="fakerecurring",
    name="Tarjeta simulada (renovación automática)",
    logo_url=None,
    min_cents=100,
    max_cents=40_000,
    currency="EUR",
)

#: El id con que se reconsulta el pago de un alta de renovacion automatica.
FAKE_RECURRING_PREFIX = "fake-sub-"


class FakePaymentProvider:
    name = "fake"
    enabled = True
    lookup_by_reference = False

    def __init__(self, api_base_url: str = "http://localhost:8000") -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.transactions: dict[str, ProviderTransaction] = {}
        #: Las altas de renovacion automatica abiertas, por su token.
        self.recurring_orders: dict[str, RecurringOrder] = {}
        #: La tarjeta que tiene guardada cada suscripcion simulada.
        self.agreements: dict[str, PaymentSource | None] = {}
        #: Los cambios de tarjeta abiertos: token -> suscripcion simulada.
        self.card_changes: dict[str, str] = {}
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

    # ---- renovacion automatica (como las suscripciones de Tipster Page)

    def recurring_method(self, country: str | None) -> PaymentMethodOption | None:
        return FAKE_RECURRING_METHOD

    def start_recurring(self, order: RecurringOrder) -> RecurringStart:
        token = uuid.uuid4().hex
        with self._lock:
            self.recurring_orders[token] = order
        with self._lock:
            self.agreements[f"fake-agreement-{token}"] = None
        return RecurringStart(
            checkout_url=f"{self.api_base_url}/dev/fake-checkout/subscription/{token}",
            transaction_id=f"{FAKE_RECURRING_PREFIX}{token}",
            agreement_id=f"fake-agreement-{token}",
        )

    def recurring_order(self, token: str) -> RecurringOrder | None:
        with self._lock:
            return self.recurring_orders.get(token)

    def resolve_recurring(self, token: str, outcome: str) -> ProviderTransaction | None:
        """Lo que hace el boton de la pagina del alta. `approved` guarda una
        tarjeta que paga las renovaciones; `approved_declining`, una que las
        rechaza; `declined` no guarda nada. None si el alta no existe."""
        order = self.recurring_order(token)
        if order is None:
            return None
        approved = outcome in ("approved", "approved_declining")
        suffix = "ok" if outcome == "approved" else "declined"
        transaction = ProviderTransaction(
            id=f"{FAKE_RECURRING_PREFIX}{token}",
            reference=order.reference,
            status="approved" if approved else "declined",
            amount_cents=order.amount_cents,
            currency=order.currency,
            status_message=None if approved else "Rechazado en la pasarela simulada",
            saved_source=(
                PaymentSource(
                    id=f"fake-source-{suffix}-{uuid.uuid4().hex[:8]}",
                    type="CARD",
                    brand="VISA",
                    last4="4242",
                    agreement_id=f"fake-agreement-{token}",
                )
                if approved
                else None
            ),
        )
        with self._lock:
            self.transactions[transaction.id] = transaction
            if transaction.saved_source is not None:
                self.agreements[f"fake-agreement-{token}"] = transaction.saved_source
        return transaction

    def card_change_url(self, source: PaymentSource, *, recovery: bool, reference: str) -> str:
        if source.agreement_id is None or source.agreement_id not in self.agreements:
            raise PaymentSourceRejected("La suscripcion simulada no existe")
        token = uuid.uuid4().hex
        with self._lock:
            self.card_changes[token] = source.agreement_id
        return f"{self.api_base_url}/dev/fake-checkout/card/{token}"

    def resolve_card_change(self, token: str, outcome: str) -> PaymentSource | None:
        """Lo que hace el boton de la pagina del cambio de tarjeta: `approved`
        guarda una tarjeta que paga; `approved_declining`, una que rechaza."""
        with self._lock:
            agreement = self.card_changes.pop(token, None)
        if agreement is None:
            return None
        suffix = "ok" if outcome == "approved" else "declined"
        source = PaymentSource(
            id=f"fake-source-{suffix}-{uuid.uuid4().hex[:8]}",
            type="CARD",
            brand="MASTERCARD",
            last4="5454",
            agreement_id=agreement,
        )
        with self._lock:
            self.agreements[agreement] = source
        return source

    def saved_source(self, agreement_id: str) -> PaymentSource | None:
        with self._lock:
            return self.agreements.get(agreement_id)

    def delete_saved_source(self, source: PaymentSource, *, reference: str) -> None:
        with self._lock:
            if source.agreement_id is not None:
                self.agreements[source.agreement_id] = None

    def charge(
        self,
        *,
        reference: str,
        amount_cents: int,
        currency: str,
        customer_email: str,
        source: PaymentSource,
        period: ChargePeriod,
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
