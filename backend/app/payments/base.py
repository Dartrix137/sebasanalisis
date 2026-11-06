"""Proveedor de pagos (docs/PLATAFORMA_COMPLETA.md §3.10, "Pasarela").

El resto de la aplicacion habla con `PaymentProvider`, nunca con una pasarela
concreta: una pasarela nueva es otra implementacion, no una reescritura. Es el
mismo patron de `core/email.EmailSender`.

Cual implementacion se usa es configuracion (`PAYMENT_PROVIDER`):

- `none` (por defecto): sin pasarela, el pago esta apagado
  (`UnconfiguredPaymentProvider`).
- `tipsterpage`: Tipster Page, integracion V2 sin landing
  (`payments/tipsterpage.py`, Fase 5, paso 5.3).
- `fake`: pasarela simulada para desarrollo y tests de punta a punta
  (`payments/fake.py`). Nunca en produccion.

Lo que el proveedor dice de una transaccion solo se cree cuando sale de
`fetch_transaction`, que es la reconsulta contra su API (§3.1): ni el cuerpo de
un webhook ni lo que mande el navegador mueven una suscripcion.
"""

import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal, Protocol

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Estado de una transaccion, ya traducido del vocabulario del proveedor.
TransactionStatus = Literal["pending", "approved", "declined", "voided", "error"]

#: Los datos del comprador que una pasarela puede pedir para un medio de pago.
#: Viajan a la pasarela y no se guardan: ni en la base, ni en un log, ni en el
#: monitoreo (decidido el 2026-11-03).
BuyerField = Literal["firstName", "lastName", "personalId", "phone"]
BUYER_FIELDS: tuple[BuyerField, ...] = ("firstName", "lastName", "personalId", "phone")

#: Tipo de un medio de pago guardado para la renovacion automatica. Lo define
#: cada pasarela; la base lo guarda como texto (hasta 16 caracteres).
PaymentSourceType = str


class PaymentProviderError(RuntimeError):
    """El proveedor no respondio o respondio algo que no se entiende."""


class PaymentsUnavailable(PaymentProviderError):
    """No hay pasarela configurada, o no ofrece esta operacion."""


class PaymentSourceRejected(PaymentProviderError):
    """El proveedor no acepto el medio de pago (token vencido, sin aprobar...)."""


class CheckoutRejected(PaymentProviderError):
    """La pasarela rechazo la orden: no se creo nada del lado de ella."""


class ProviderMisconfigured(RuntimeError):
    """La configuracion de la pasarela no sirve: la API no arranca."""


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
    # El producto que el proveedor dice que se pago (`plans.code`), si lo
    # informa. Si no coincide con el plan del pago, no se concede nada.
    product_code: str | None = None


@dataclass(frozen=True)
class PaymentMethodOption:
    """Un medio de pago que la pasarela ofrece, para pintar el formulario."""

    key: str
    name: str
    logo_url: str | None
    #: El rango de monto que admite, en centavos de `currency`. Ambos incluidos.
    min_cents: int
    max_cents: int
    currency: str
    #: Paises donde aplica (ISO 3166-1 alfa-2). Vacio = sin restriccion.
    countries: tuple[str, ...] = ()
    #: Los datos del comprador que pide.
    fields: tuple[BuyerField, ...] = ()


@dataclass(frozen=True)
class CheckoutOrder:
    """Lo que hace falta para abrir el pago de una referencia en la pasarela."""

    reference: str
    amount_cents: int
    currency: str
    #: `plans.code`. La reconsulta lo compara.
    product_code: str
    #: Sin tildes ni caracteres fuera de ASCII (`billing/checkout_text.py`).
    product_name: str
    product_description: str
    method: str
    country: str | None
    url_ok: str
    url_ko: str
    notification_url: str
    #: Solo los campos que pide el medio. Nunca se guardan.
    buyer: Mapping[BuyerField, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckoutPage:
    """La pagina que el navegador abre para pagar: HTML que la API le sirve
    una sola vez (`core/checkout_pages.py`)."""

    html: str


@dataclass(frozen=True)
class TokenizerInfo:
    """Lo que el frontend necesita para pedirle al proveedor un token."""

    #: `fake`: selector de la pasarela simulada. Ninguna pasarela real tokeniza
    #: hoy: Tipster Page no tiene cobros recurrentes (2026-11-03).
    kind: Literal["fake"]


@dataclass(frozen=True)
class ProviderEvent:
    """Un webhook ya leido.

    `event_id` es la llave de idempotencia, junto con la pasarela
    (`payment_events.provider`, `payment_events.provider_event_id`). Un evento
    sin firma valida lleva un id de otro espacio de nombres, para que un evento
    falsificado no pueda ocupar el id de uno autentico.
    """

    event_id: str
    event_type: str
    signature_verified: bool
    # Solo se usa si la firma es valida, y solo para saber que reconsultar.
    transaction_id: str | None
    status: str
    payload: dict[str, Any] | None
    # True = un aviso que la pasarela manda y que no mueve nada (la devolucion
    # de Tipster Page): se guarda y se responde 200, sin reconsultar, para que
    # no se reintente. Vale con firma valida o sin ella.
    notice_only: bool = False


class PaymentProvider(Protocol):
    name: str
    #: False = no se puede cobrar (faltan las llaves).
    enabled: bool
    #: True = la transaccion se reconsulta con la referencia del pago: la
    #: pasarela no tiene un id de transaccion propio (Tipster Page).
    lookup_by_reference: bool

    def describe(self) -> str:
        """Contra que ambiente quedo, para el log de arranque. Sin llaves."""
        ...

    def payment_methods(self, country: str | None) -> list[PaymentMethodOption]:
        """Los medios que se ofrecen en un pais. `None`: los que no dependen
        del pais."""
        ...

    def start_checkout(self, order: CheckoutOrder) -> CheckoutPage:
        """Crea la orden en la pasarela y devuelve la pagina con la que el
        navegador sigue al procesador. Se llama una sola vez por pago.
        `CheckoutRejected` si la pasarela no la acepta."""
        ...

    def parse_event(self, body: bytes, headers: Mapping[str, str]) -> ProviderEvent:
        """Lee un webhook y dice si su firma es valida. Nunca lanza."""
        ...

    def fetch_transaction(self, transaction_id: str) -> ProviderTransaction | None:
        """Reconsulta una transaccion. None si el proveedor no la conoce."""
        ...

    def tokenizer(self) -> TokenizerInfo | None:
        """Como obtiene el navegador el token de un medio de pago. None si no
        se pueden guardar medios de pago (no hay renovacion automatica)."""
        ...

    def create_payment_source(
        self, *, source_type: PaymentSourceType, token: str, customer_email: str
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
    lookup_by_reference = False

    def describe(self) -> str:
        return "sin pasarela configurada: el pago esta apagado"

    def payment_methods(self, country: str | None) -> list[PaymentMethodOption]:
        raise PaymentsUnavailable("No hay pasarela de pagos configurada")

    def start_checkout(self, order: CheckoutOrder) -> CheckoutPage:
        raise PaymentsUnavailable("No hay pasarela de pagos configurada")

    def parse_event(self, body: bytes, headers: Mapping[str, str]) -> ProviderEvent:
        # Sin secreto no hay como verificar nada.
        return unverified_event(self.name, body, None)

    def fetch_transaction(self, transaction_id: str) -> ProviderTransaction | None:
        raise PaymentsUnavailable("No hay pasarela de pagos configurada")

    def tokenizer(self) -> TokenizerInfo | None:
        return None

    def create_payment_source(
        self, *, source_type: PaymentSourceType, token: str, customer_email: str
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
    # Import aqui: `fake` y `tipsterpage` importan este modulo.
    from app.payments import tipsterpage
    from app.payments.fake import FakePaymentProvider

    # Antes que nada: con llaves de produccion no arranca una configuracion de
    # desarrollo (pasarela simulada, correo a archivo).
    tipsterpage.check_startup(settings)
    if settings.payment_provider == "fake":
        return FakePaymentProvider(api_base_url=settings.api_public_url)
    if settings.payment_provider == "tipsterpage":
        return tipsterpage.from_settings(settings)
    return UnconfiguredPaymentProvider()


@lru_cache
def get_payment_provider() -> PaymentProvider:
    """Dependencia de FastAPI. Los tests la sustituyen."""
    return build_payment_provider(get_settings())
