"""Pasarela simulada: desarrollo y tests de punta a punta. Nunca en produccion.

Con `PAYMENT_PROVIDER=fake` el boton de pagar lleva a una pagina de la propia
API (`api/v1/fake_checkout.py`) con dos botones, aprobar y rechazar, que anotan
el resultado aqui, en memoria. La aplicacion lo lee con `fetch_transaction`,
igual que reconsulta a una pasarela real: el resto del flujo es el de verdad.

No cobra nada.
"""

import json
import threading
import uuid
from collections.abc import Mapping
from urllib.parse import urlencode

from app.payments.base import (
    Acceptance,
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
FAKE_ACCEPTANCE = "fake-acceptance"
FAKE_PERSONAL_DATA = "fake-personal-data"

# Cabecera con la que un test marca un webhook simulado como autentico.
FAKE_SIGNATURE_HEADER = "x-fake-signature"
FAKE_SIGNATURE = "valida"


class FakePaymentProvider:
    name = "fake"
    enabled = True

    def __init__(self, api_base_url: str = "http://localhost:8000") -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.transactions: dict[str, ProviderTransaction] = {}
        self._lock = threading.Lock()

    def describe(self) -> str:
        return "pasarela SIMULADA (PAYMENT_PROVIDER=fake): no cobra nada"

    def checkout_url(
        self,
        *,
        reference: str,
        amount_cents: int,
        currency: str,
        redirect_url: str,
        customer_email: str,
    ) -> str:
        params = {
            "reference": reference,
            "amount_cents": str(amount_cents),
            "currency": currency,
            "redirect_url": redirect_url,
        }
        return f"{self.api_base_url}/dev/fake-checkout?{urlencode(params)}"

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

    def acceptance(self) -> Acceptance:
        return Acceptance(
            acceptance_token=FAKE_ACCEPTANCE,
            terms_url=f"{self.api_base_url}/dev/fake-checkout/terminos",
            personal_data_token=FAKE_PERSONAL_DATA,
            personal_data_url=f"{self.api_base_url}/dev/fake-checkout/datos",
        )

    def create_payment_source(
        self,
        *,
        source_type: PaymentSourceType,
        token: str,
        customer_email: str,
        acceptance_token: str,
        personal_data_token: str,
    ) -> PaymentSource:
        if (acceptance_token, personal_data_token) != (FAKE_ACCEPTANCE, FAKE_PERSONAL_DATA):
            raise PaymentSourceRejected("Faltan los contratos aceptados")
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
