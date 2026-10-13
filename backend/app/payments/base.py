"""Proveedor de pagos (docs/PLATAFORMA_COMPLETA.md §3.10, "Pasarela").

El resto de la aplicacion habla con `PaymentProvider`, nunca con Wompi: una
segunda pasarela es otra implementacion, no una reescritura. Es el mismo patron
de `core/email.EmailSender`.

Cual implementacion se usa es configuracion (`PAYMENT_PROVIDER`):

- `wompi`: produccion y sandbox (`payments/wompi.py`). Sin llaves, el pago queda
  apagado (`UnconfiguredPaymentProvider`).
- `fake`: pasarela simulada para desarrollo y tests de punta a punta
  (`payments/fake.py`). Nunca en produccion.

Lo que el proveedor dice de una transaccion solo se cree cuando sale de
`fetch_transaction`, que es la reconsulta contra su API (§3.1): ni el cuerpo de
un webhook ni lo que mande el navegador mueven una suscripcion.
"""

import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal, Protocol

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Estado de una transaccion, ya traducido del vocabulario del proveedor.
TransactionStatus = Literal["pending", "approved", "declined", "voided", "error"]


class PaymentProviderError(RuntimeError):
    """El proveedor no respondio o respondio algo que no se entiende."""


class PaymentsUnavailable(PaymentProviderError):
    """No hay pasarela configurada."""


@dataclass(frozen=True)
class ProviderTransaction:
    """Una transaccion tal como la reporta la API del proveedor."""

    id: str
    reference: str
    status: TransactionStatus
    amount_cents: int
    currency: str
    # Texto del proveedor sobre el resultado. Queda en la base, no se le muestra
    # tal cual al cliente.
    status_message: str | None = None


@dataclass(frozen=True)
class ProviderEvent:
    """Un webhook ya leido.

    `event_id` es la llave de idempotencia (`payment_events.provider_event_id`).
    Un evento sin firma valida lleva un id de otro espacio de nombres, para que
    un evento falsificado no pueda ocupar el id de uno autentico.
    """

    event_id: str
    event_type: str
    signature_verified: bool
    # Solo se usa si la firma es valida, y solo para saber que reconsultar.
    transaction_id: str | None
    status: str
    payload: dict[str, Any] | None


class PaymentProvider(Protocol):
    name: str
    #: False = no se puede cobrar (faltan las llaves).
    enabled: bool

    def describe(self) -> str:
        """Contra que ambiente quedo, para el log de arranque. Sin llaves."""
        ...

    def checkout_url(
        self,
        *,
        reference: str,
        amount_cents: int,
        currency: str,
        redirect_url: str,
        customer_email: str,
    ) -> str:
        """La pagina del proveedor donde el cliente paga esta referencia."""
        ...

    def parse_event(self, body: bytes, headers: Mapping[str, str]) -> ProviderEvent:
        """Lee un webhook y dice si su firma es valida. Nunca lanza."""
        ...

    def fetch_transaction(self, transaction_id: str) -> ProviderTransaction | None:
        """Reconsulta una transaccion. None si el proveedor no la conoce."""
        ...


def unverified_event(provider: str, body: bytes, payload: dict[str, Any] | None) -> ProviderEvent:
    """Evento que no paso la verificacion: se guarda para auditar, no mueve nada."""
    event_type = payload.get("event") if isinstance(payload, dict) else None
    return ProviderEvent(
        event_id=f"{provider}:invalid:{hashlib.sha256(body).hexdigest()}",
        event_type=event_type if isinstance(event_type, str) else "unknown",
        signature_verified=False,
        transaction_id=None,
        status="invalid_signature",
        payload=payload,
    )


class UnconfiguredPaymentProvider:
    """`PAYMENT_PROVIDER=wompi` sin llaves: el pago esta apagado."""

    name = "wompi"
    enabled = False

    def describe(self) -> str:
        return "sin configurar (faltan las llaves): el pago esta apagado"

    def checkout_url(
        self,
        *,
        reference: str,
        amount_cents: int,
        currency: str,
        redirect_url: str,
        customer_email: str,
    ) -> str:
        raise PaymentsUnavailable("No hay pasarela de pagos configurada")

    def parse_event(self, body: bytes, headers: Mapping[str, str]) -> ProviderEvent:
        # Sin secreto no hay como verificar nada.
        return unverified_event(self.name, body, None)

    def fetch_transaction(self, transaction_id: str) -> ProviderTransaction | None:
        raise PaymentsUnavailable("No hay pasarela de pagos configurada")


def build_payment_provider(settings: Settings) -> PaymentProvider:
    # Imports aqui: `wompi` y `fake` importan este modulo.
    from app.payments.fake import FakePaymentProvider
    from app.payments.wompi import WompiProvider, has_production_keys, wompi_keys_present

    if settings.payment_provider == "fake":
        if has_production_keys(settings):
            raise ValueError(
                "PAYMENT_PROVIDER=fake con llaves de produccion de Wompi: la pasarela "
                "simulada aprueba pagos sin cobrar. Usa PAYMENT_PROVIDER=wompi."
            )
        return FakePaymentProvider(api_base_url=settings.api_public_url)
    if not wompi_keys_present(settings):
        return UnconfiguredPaymentProvider()
    return WompiProvider.from_settings(settings)


@lru_cache
def get_payment_provider() -> PaymentProvider:
    """Dependencia de FastAPI. Los tests la sustituyen."""
    return build_payment_provider(get_settings())
