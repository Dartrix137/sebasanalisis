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

La renovacion automatica (paso 5.3b, decidido el 2026-11-17) empieza en una
pagina de la pasarela: el cliente paga ahi el primer periodo y la tarjeta queda
guardada en una suscripcion del lado de la pasarela (`start_recurring`). Cada
renovacion la cobra despues la aplicacion contra esa suscripcion (`charge`),
cuando lo decide `billing/schedule.py`.

Lo que el proveedor dice de una transaccion solo se cree cuando sale de
`fetch_transaction`, que es la reconsulta contra su API (§3.1): ni el cuerpo de
un webhook ni lo que mande el navegador mueven una suscripcion.
"""

import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
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
    #: La suscripcion del lado de la pasarela a la que pertenece el medio, si
    #: cobra contra una (Tipster Page). `subscriptions.provider_subscription_id`.
    agreement_id: str | None = None


@dataclass(frozen=True)
class ChargePeriod:
    """El periodo que paga un cobro de renovacion.

    `key` es el mismo en todos los intentos del periodo y distinto en cada
    periodo; `end` es hasta cuando vale si se aprueba. Una pasarela que
    controla los periodos (Tipster Page) los exige iguales en cada reintento.
    """

    key: str
    end: datetime


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
    #: El medio que quedo guardado con este pago, en el alta de una renovacion
    #: automatica que se paga en la pagina de la pasarela. Si se aprueba, la
    #: suscripcion se renueva con el.
    saved_source: "PaymentSource | None" = None
    #: Un cobro rechazado que admite otro intento con la misma tarjeta. False:
    #: hay que cambiarla antes (Tipster Page, `retry_allowed`). None: no se sabe.
    retry_allowed: bool | None = None
    #: El banco pide que el titular se autentique (3DS) para completar el
    #: cobro, que queda pendiente: el enlace para hacerlo.
    authentication_url: str | None = None


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
    #: Fuera de la zona euro cobra en dolares (USD), no en `currency`: la
    #: pantalla de pago lo avisa al elegirlo.
    usd_outside_eurozone: bool = False


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
class RecurringOrder:
    """El alta de una renovacion automatica en la pagina de la pasarela.

    El cliente paga ahi el primer periodo, por `amount_cents`, y la tarjeta
    queda guardada para los siguientes. `reference` es la del pago del alta.
    """

    reference: str
    amount_cents: int
    currency: str
    #: `plans.code` y el nombre del plan, sin tildes (`billing/checkout_text`).
    product_code: str
    product_name: str
    interval: str
    interval_count: int
    email: str
    country: str
    language: str
    url_ok: str
    url_ko: str
    notification_url: str
    #: Solo verifica y guarda la tarjeta, por 0, sin cobrar el primer periodo:
    #: pasar a renovacion automatica con un periodo ya pagado (paso 5.3b).
    #: `amount_cents` es entonces lo que costara cada renovacion.
    setup_only: bool = False


@dataclass(frozen=True)
class RecurringStart:
    """El alta ya creada en la pasarela."""

    #: La pagina de la pasarela donde el cliente paga y guarda la tarjeta.
    checkout_url: str
    #: Con que se reconsulta el pago del alta (`fetch_transaction`).
    transaction_id: str
    #: La suscripcion del lado de la pasarela, si la hay.
    agreement_id: str | None = None


@dataclass(frozen=True)
class CheckoutPage:
    """La pagina que el navegador abre para pagar: HTML que la API le sirve
    una sola vez (`core/checkout_pages.py`)."""

    html: str


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
    #: Un aviso de una suscripcion del lado de la pasarela: su id y nuestra
    #: referencia del alta (`external_id` en Tipster Page). Solo dicen que
    #: pagos reconsultar; lo que se aplica sale de la reconsulta.
    agreement_id: str | None = None
    external_reference: str | None = None


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

    def recurring_method(self, country: str | None) -> PaymentMethodOption | None:
        """El medio con el que se paga una renovacion automatica en ese pais.
        None si la pasarela no la ofrece."""
        ...

    def start_recurring(self, order: RecurringOrder) -> RecurringStart:
        """Crea el alta de la renovacion automatica en la pasarela. Se llama
        una sola vez por pago. `CheckoutRejected` si no la acepta."""
        ...

    def card_change_url(self, source: PaymentSource, *, recovery: bool, reference: str) -> str:
        """La pagina de la pasarela donde el cliente cambia la tarjeta de su
        suscripcion, sin cobrar nada. `recovery`: hay un cobro rechazado que se
        reintentara con la tarjeta nueva. `reference` hace idempotente la
        llamada."""
        ...

    def saved_source(self, agreement_id: str) -> PaymentSource | None:
        """El medio que la suscripcion de la pasarela tiene guardado ahora
        (despues de un cambio de tarjeta o de una verificacion). None si
        todavia no tiene uno."""
        ...

    def delete_saved_source(self, source: PaymentSource, *, reference: str) -> None:
        """Borra el medio guardado y cancela la suscripcion de la pasarela.
        Lanza `PaymentProviderError` si no lo confirma."""
        ...

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
        """Cobra a un medio de pago guardado el periodo `period`. Devuelve la
        transaccion tal como la reporta el proveedor, a veces todavia
        `pending`."""
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

    def recurring_method(self, country: str | None) -> PaymentMethodOption | None:
        return None

    def start_recurring(self, order: RecurringOrder) -> RecurringStart:
        raise PaymentsUnavailable("No hay pasarela de pagos configurada")

    def card_change_url(self, source: PaymentSource, *, recovery: bool, reference: str) -> str:
        raise PaymentsUnavailable("No hay pasarela de pagos configurada")

    def saved_source(self, agreement_id: str) -> PaymentSource | None:
        raise PaymentsUnavailable("No hay pasarela de pagos configurada")

    def delete_saved_source(self, source: PaymentSource, *, reference: str) -> None:
        raise PaymentsUnavailable("No hay pasarela de pagos configurada")

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
