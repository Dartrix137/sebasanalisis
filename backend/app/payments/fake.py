"""Pasarela simulada: desarrollo y tests de punta a punta. Nunca en produccion.

Con `PAYMENT_PROVIDER=fake` el boton de pagar lleva a una pagina de la propia
API (`api/v1/fake_checkout.py`) con dos botones, aprobar y rechazar, que anotan
el resultado aqui, en memoria. La aplicacion lo lee con `fetch_transaction`,
igual que reconsulta a Wompi: el resto del flujo es el de verdad.

No cobra nada. `build_payment_provider` se niega a usarla si hay llaves de
produccion de Wompi configuradas.
"""

import json
import threading
import uuid
from collections.abc import Mapping
from urllib.parse import urlencode

from app.payments.base import (
    ProviderEvent,
    ProviderTransaction,
    TransactionStatus,
    unverified_event,
)

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
