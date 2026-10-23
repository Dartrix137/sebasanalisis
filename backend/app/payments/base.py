"""Proveedor de pagos (docs/PLATAFORMA_COMPLETA.md §3.10, "Pasarela").

El resto de la aplicacion habla con `PaymentProvider`, nunca con una pasarela
concreta: una pasarela nueva es otra implementacion, no una reescritura. Es el
mismo patron de `core/email.EmailSender`.

Cual implementacion se usa es configuracion (`PAYMENT_PROVIDER`):

- `none` (por defecto): sin pasarela, el pago esta apagado
  (`UnconfiguredPaymentProvider`). Es lo que corre desde que Wompi salio del
  proyecto (Fase 5, paso 5.1) hasta que se integre la pasarela nueva (5.3).
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


class PaymentSourceRejected(PaymentProviderError):
    """El proveedor no acepto el medio de pago (token vencido, sin aprobar...)."""


# Medios que se pueden guardar para la renovacion automatica (decidido el
# 2026-10-13: tarjetas y Nequi).
PaymentSourceType = Literal["CARD", "NEQUI"]
PAYMENT_SOURCE_TYPES: tuple[PaymentSourceType, ...] = ("CARD", "NEQUI")


@dataclass(frozen=True)
class Acceptance:
    """Los dos contratos del proveedor que el cliente acepta antes de guardar
    un medio de pago: los tokens viajan de vuelta al guardarlo."""

    acceptance_token: str
    terms_url: str
    personal_data_token: str
    personal_data_url: str


@dataclass(frozen=True)
class PaymentSource:
    """Un medio de pago guardado en el proveedor. Aqui nunca hay datos de
    tarjeta: solo su referencia y, para mostrar, la marca y los ultimos cuatro."""

    id: str
    type: PaymentSourceType
    brand: str | None = None
    last4: str | None = None


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
    # Marca de la tarjeta con la que se pago, si fue con tarjeta y el proveedor
    # la informa. Nunca el numero.
    card_brand: str | None = None
    card_last4: str | None = None


@dataclass(frozen=True)
class TokenizerInfo:
    """Lo que el frontend necesita para pedirle al proveedor un token."""

    #: `fake`: selector de la pasarela simulada. La pasarela nueva agrega aqui
    #: su forma de tokenizar (Fase 5, paso 5.3).
    kind: Literal["fake"]


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

    def tokenizer(self) -> TokenizerInfo | None:
        """Como obtiene el navegador el token de un medio de pago. None si no
        se pueden guardar medios de pago."""
        ...

    def acceptance(self) -> Acceptance:
        """Los contratos del proveedor que el cliente debe aceptar."""
        ...

    def create_payment_source(
        self,
        *,
        source_type: PaymentSourceType,
        token: str,
        customer_email: str,
        acceptance_token: str,
        personal_data_token: str,
    ) -> PaymentSource:
        """Guarda el medio de pago que el cliente tokenizo en su navegador.
        Lanza `PaymentSourceRejected` si el proveedor no lo acepta."""
        ...

    def charge(
        self,
        *,
        reference: str,
        amount_cents: int,
        currency: str,
        customer_email: str,
        source: PaymentSource,
    ) -> ProviderTransaction:
        """Cobra a un medio de pago guardado. Devuelve la transaccion tal como
        la reporta el proveedor, casi siempre todavia `pending`."""
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
    """Sin pasarela configurada: el pago esta apagado."""

    name = "none"
    enabled = False

    def describe(self) -> str:
        return "sin pasarela configurada: el pago esta apagado"

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

    def tokenizer(self) -> TokenizerInfo | None:
        return None

    def acceptance(self) -> Acceptance:
        raise PaymentsUnavailable("No hay pasarela de pagos configurada")

    def create_payment_source(
        self,
        *,
        source_type: PaymentSourceType,
        token: str,
        customer_email: str,
        acceptance_token: str,
        personal_data_token: str,
    ) -> PaymentSource:
        raise PaymentsUnavailable("No hay pasarela de pagos configurada")

    def charge(
        self,
        *,
        reference: str,
        amount_cents: int,
        currency: str,
        customer_email: str,
        source: PaymentSource,
    ) -> ProviderTransaction:
        raise PaymentsUnavailable("No hay pasarela de pagos configurada")


def build_payment_provider(settings: Settings) -> PaymentProvider:
    # Import aqui: `fake` importa este modulo.
    from app.payments.fake import FakePaymentProvider

    if settings.payment_provider == "fake":
        return FakePaymentProvider(api_base_url=settings.api_public_url)
    return UnconfiguredPaymentProvider()


@lru_cache
def get_payment_provider() -> PaymentProvider:
    """Dependencia de FastAPI. Los tests la sustituyen."""
    return build_payment_provider(get_settings())
