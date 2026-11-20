"""Tipster Page: integracion V2 sin landing (Fase 5, paso 5.3).

Fuente de todo lo que sigue, leida el 2026-11-04:

- El manual oficial "Documentacion de integracion -- Plataforma de pago
  Tipsterpage tsPay v2", v2.0 del 2026-10-29
  (`docs/docs tipsterpage/MANUAL_INTEGRACION_API_PAGOS_TSPAY_V2_NO_LANDING.pdf`,
  fuera del repositorio). Las secciones se citan como "manual §N". Revisado
  contra la v2.2 del 2026-11-10 (`... (1).pdf`, leida el 2026-11-13): la firma,
  el aviso y la reconsulta no cambian. Suma `GET /health` (§11), el dato
  `email` del comprador (solo `vpay`) y medios nuevos (Stripe, IBIS, Binance
  Pay), que se cobran en otra moneda pero se firman y se reconsultan en EUR.
- Su OpenAPI, `https://apiekans.tipster.page/tspayv2/docs` (v2.0.0, con
  usuario y contrasena), citado como "OpenAPI".

Nunca de memoria (CLAUDE.md, "Pagos: reglas no negociables"). El flujo:

1. `payment_methods`: el catalogo de medios por pais (manual §5).
2. `start_checkout`: crea la orden firmada; la respuesta es HTML que lleva al
   navegador al procesador (Redsys o EBANX) (manual §7).
3. `parse_event`: el aviso de pago a `notification_url`, firmado (manual §9).
4. `fetch_transaction`: la reconsulta del estado de la orden (manual §10). Es
   lo unico que mueve un pago (`core/subscriptions.apply_transaction`).

Tipster Page no tiene un id de transaccion propio: la orden se identifica con
nuestro `order_id`, que es `payments.reference` (`lookup_by_reference`). Cobra
siempre en euros, con dos decimales (manual §7, `amount`).

La renovacion automatica (paso 5.3b, 2026-11-17) va por sus suscripciones, con
Solidgate y solo con tarjeta: `start_recurring` crea el alta y el cliente paga
el primer periodo en la pagina de Solidgate; `charge` cobra cada renovacion
cuando la aplicacion lo decide (modo `MERCHANT_MANAGED`). Fuente: el OpenAPI,
rutas `/tspayv2/subscriptions...`, y `tspay-subscriptions.md` (2026-11-17),
citado como "suscripciones §N". La firma es otra, canonica
(`payments/tipsterpage_signing.py`). No tokeniza en el navegador.

Los datos del comprador que pide un medio (`firstName`, `lastName`,
`personalId`, `phone`) van solo en el cuerpo de la orden: nunca en un log, ni
en una excepcion, ni en la base.
"""

import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from collections.abc import Mapping
from datetime import UTC
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.core.config import Settings
from app.payments.base import (
    BUYER_FIELDS,
    BuyerField,
    ChargePeriod,
    CheckoutOrder,
    CheckoutPage,
    CheckoutRejected,
    PaymentMethodOption,
    PaymentProviderError,
    PaymentSource,
    ProviderEvent,
    ProviderMisconfigured,
    ProviderTransaction,
    RecurringOrder,
    RecurringStart,
    TransactionStatus,
    unverified_event,
)
from app.payments.tipsterpage_signing import (
    Action,
    amount_number,
    signed_body,
    verified_notification,
)

logger = logging.getLogger(__name__)

NAME = "tipsterpage"
CURRENCY = "EUR"

# Manual §3: las dos URL base, con el prefijo de version incluido.
SANDBOX_BASE_URL = "https://sandboxv2.ttpgpay.com/tspayv2"
PRODUCTION_BASE_URL = "https://paymentsv2.ttpgpay.com/tspayv2"

#: Los medios de cripto no se ofrecen (decidido por el usuario el 2026-11-13):
#: `payid19` (factura de PayID19 en cripto) y `binancepay` (Binance Pay, en
#: USD), segun la descripcion de `payment_method` en el OpenAPI. Se quitan del
#: catalogo, asi que tampoco pasan la validacion de una orden
#: (`core/subscriptions`). Un medio de cripto nuevo hay que sumarlo aqui.
EXCLUDED_METHODS = frozenset({"payid19", "binancepay"})

#: Los siete medios de Stripe Checkout (OpenAPI, `payment_method`:
#: `PAYMENT_METHODS_STRIPE_IDS`): cobran en EUR a un comprador de la zona euro y
#: en USD a los demas. Se firman y se reconsultan en EUR igual que el resto.
STRIPE_METHODS = frozenset({
    "stripe",
    "klarna-stripe",
    "google-pay",
    "apple-pay",
    "stripe-amazon-pay",
    "revolut-stripe",
    "multibanco-stripe",
})

#: El catalogo trae medios repetidos con el mismo nombre, uno de Redsys y otro
#: de Stripe. El de Stripe se distingue y el de Redsys queda con el nombre del
#: catalogo:
#: - "Tarjeta de credito/debito": `cardtpv` y `stripe` (decidido por el usuario
#:   el 2026-11-13);
#: - "Google Pay": `google-apple-pay` y `google-pay` (2026-11-19).
DISPLAY_NAMES = {
    "stripe": "Tarjeta de crédito/débito (Stripe)",
    "google-pay": "Google Pay (Stripe)",
}

#: Manual §7.1: el orden fijo de los campos que entran en `tspay_signature`.
ORDER_SIGNATURE_FIELDS = (
    "order_id",
    "product_id",
    "product_name",
    "product_description",
    "amount",
    "payment_method",
    "url_ok",
    "url_ko",
    "notification_url",
    "country",
)

#: Manual §10 y OpenAPI (`PaidOrderStatus`): los estados de una orden, en el
#: vocabulario de `ProviderTransaction`.
#:
#: - `paid`: pago completado, terminal.
#: - `error`: fallido o denegado. Puede pasar a `paid` si el comprador reintenta
#:   la misma operacion: un pago rechazado todavia admite una aprobacion que
#:   venga de la reconsulta (`core/subscriptions._resolvable`).
#: - `expired`: la orden caduco.
#: - `error_and_refund_payment`: error con reembolso asociado. Mientras se
#:   prueba en el sandbox, no aprobado (pregunta 7 de "Paso 5.3").
#: - `fraud`: terminal; el monto, la moneda, el medio o el pais del pago no son
#:   los de la orden. Queda en `error` para que alguien lo mire.
STATUS_MAP: dict[str, TransactionStatus] = {
    "pending": "pending",
    "paid": "approved",
    "error": "declined",
    "expired": "declined",
    "error_and_refund_payment": "declined",
    "fraud": "error",
}

#: Manual §9: `paid_status` del aviso.
NOTIFICATION_STATUSES = ("ok", "ko")

#: Tope del `paid_status` de un aviso que no es de pago (cabe en
#: `payment_events.status`).
MAX_NOTICE_STATUS_LENGTH = 50

#: El catalogo cambia poco; con esto no se le pide en cada pantalla.
CATALOG_TTL_SECONDS = 300.0

# ---- suscripciones (paso 5.3b)

#: OpenAPI, `TspaySubscriptionMethod`: el unico medio de las suscripciones.
RECURRING_METHOD = "solidgate"

#: OpenAPI, `periodicity`: la duracion de un plan en su vocabulario. Un plan
#: con otra duracion no se ofrece con renovacion automatica.
PERIODICITIES: dict[tuple[str, int], str] = {
    ("month", 1): "mensual",
    ("month", 2): "bimestral",
    ("month", 3): "trimestral",
    ("month", 6): "semestral",
    ("year", 1): "anual",
}

#: OpenAPI, `TspaySubscriptionChargeResult.status`, en el vocabulario de
#: `ProviderTransaction`. `REVIEW_REQUIRED` es un cobro con un resultado
#: ambiguo (un timeout): sigue pendiente hasta que la reconsulta diga otra cosa.
CHARGE_STATUS_MAP: dict[str, TransactionStatus] = {
    "SUBMITTING": "pending",
    "PENDING": "pending",
    "REVIEW_REQUIRED": "pending",
    "PAID": "approved",
    "FAILED": "declined",
    "REFUNDED": "voided",
}

#: Suscripciones §3.2: el primer cobro, el que se paga en la pagina de Solidgate,
#: lleva este `period_id`.
INITIAL_PERIOD = "initial"

#: Los pagos de una suscripcion se reconsultan con un id que armamos nosotros:
#: `sub:<suscripcion>:<pago o initial>:<nuestra referencia>`. Lo guarda
#: `payments.provider_transaction_id`: sale siempre de nuestra base.
SUBSCRIPTION_TX_PREFIX = "sub"

#: Suscripciones §3.2: el aviso de una devolucion. No mueve nada, como la de
#: una orden: se registra a mano en el admin (decidido el 2026-11-06).
REFUND_EVENT = "subscription.payment_refunded"

# Las claves de idempotencia salen de nuestra referencia: repetir la misma
# llamada (un timeout) no repite la operacion (suscripciones §2.6).
_IDEMPOTENCY_NAMESPACE = uuid.UUID("5a3e1c2b-7d4f-4b8e-9a61-3c0f2e8d7b15")

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


# ---------------------------------------------------------------- firmas


def format_amount(amount_cents: int) -> str:
    """Manual §7, `amount`: euros con dos decimales, `NN.DD`. `3200` -> `"32.00"`."""
    if amount_cents <= 0:
        raise ValueError("El monto debe ser positivo")
    units, cents = divmod(amount_cents, 100)
    return f"{units}.{cents:02d}"


def order_signature(secret_key: str, params: Mapping[str, str]) -> str:
    """Manual §7.1: `tspay_signature = HMAC_SHA256(SECRET_KEY, S)` en hexadecimal.

    `S` es la concatenacion, sin separador y en el orden fijo de
    `ORDER_SIGNATURE_FIELDS`, de los valores tal como se envian. Un campo
    ausente aporta `""`. Los datos del comprador no entran.
    """
    message = "".join(params.get(name, "") for name in ORDER_SIGNATURE_FIELDS)
    return hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()


def notification_signature(secret_key: str, paid_status: str, order_id: str, amount: str) -> str:
    """Manual §9.1: `nt_signature = HMAC_SHA256(SECRET_KEY, paid_status + order_id + amount)`.

    `amount` va exactamente como llego en el cuerpo del aviso (`12.5`, no
    `12.50`; `10`, no `10.00`). El OpenAPI lo precisa: es el numero JSON
    serializado con `String(amount)` de JavaScript.
    """
    message = f"{paid_status}{order_id}{amount}"
    return hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()


def _raw_json(body: bytes) -> Any:
    """El JSON con los numeros como el texto que llego (`12.5` -> `"12.5"`).

    Es lo que pide el manual §9.1 para firmar `amount`: el texto crudo, no un
    numero reformateado.
    """
    return json.loads(body, parse_float=str, parse_int=str)


def _euro_cents(value: Any) -> int | None:
    """`12.5` -> 1250. None si no es un monto en euros con a lo sumo dos
    decimales. Sin `float`: el numero llega como `Decimal`."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount < 0:
        return None
    cents = amount * 100
    if cents != cents.to_integral_value():
        return None
    return int(cents)


# ---------------------------------------------------------------- proveedor


class TipsterPageProvider:
    name = NAME
    enabled = True
    lookup_by_reference = True

    def __init__(
        self,
        *,
        base_url: str,
        merchant_code: str,
        auth_bearer: str,
        secret_key: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._secret_key = secret_key
        # Suscripciones §2.1: `merchant` es el de `X-TSPAY-USER`, sin espacios.
        self._merchant = merchant_code.strip()
        # Manual §4: las dos cabeceras de todas las llamadas.
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "X-TSPAY-USER": merchant_code,
                "Authorization": f"Bearer {auth_bearer}",
            },
            timeout=_TIMEOUT,
            transport=transport,
            follow_redirects=False,
        )
        self._catalog: dict[str, tuple[float, list[PaymentMethodOption]]] = {}
        self._lock = threading.Lock()

    @property
    def production(self) -> bool:
        return self.base_url == PRODUCTION_BASE_URL

    def describe(self) -> str:
        return f"Tipster Page ({'PRODUCCION' if self.production else 'sandbox'})"

    # ---- catalogo (manual §5)

    def payment_methods(self, country: str | None) -> list[PaymentMethodOption]:
        """Manual §5: `GET /payment-methods?country-code=`.

        Con pais, la pasarela devuelve los medios de ese pais mas los que no
        tienen restriccion. Sin pais devuelve todo el catalogo: aqui se dejan
        solo los que no dependen del pais.
        """
        key = country or ""
        now = time.monotonic()
        with self._lock:
            cached = self._catalog.get(key)
            if cached is not None and cached[0] > now:
                return cached[1]
        params = {"country-code": country} if country else None
        response = self._request("GET", "/payment-methods", params=params)
        if response.status_code != 200:
            raise PaymentProviderError(f"Catalogo de medios: HTTP {response.status_code}")
        items = _json(response)
        if not isinstance(items, list):
            raise PaymentProviderError("Catalogo de medios: respuesta inesperada")
        methods = [m for m in (_method(item) for item in items) if m is not None]
        if country is None:
            methods = [m for m in methods if not m.countries]
        with self._lock:
            self._catalog[key] = (now + CATALOG_TTL_SECONDS, methods)
        return methods

    # ---- orden (manual §7)

    def start_checkout(self, order: CheckoutOrder) -> CheckoutPage:
        """Manual §7: `POST /create-order-tspay`, con los campos en claro y
        `tspay_signature` (§7.1). La respuesta 201 es HTML (§7.2)."""
        if order.currency != CURRENCY:
            raise CheckoutRejected("Tipster Page solo cobra en euros")
        params: dict[str, str] = {
            "order_id": order.reference,
            "product_id": order.product_code,
            "product_name": order.product_name,
            "product_description": order.product_description,
            "amount": format_amount(order.amount_cents),
            "payment_method": order.method,
            "url_ok": order.url_ok,
            "url_ko": order.url_ko,
            "notification_url": order.notification_url,
        }
        if order.country:
            # Manual §7: obligatorio con EBANX, opcional con Redsys.
            params["country"] = order.country
        body: dict[str, str] = {
            **params,
            "tspay_signature": order_signature(self._secret_key, params),
        }
        # Manual §6 y §7: los datos del comprador van como campos sueltos y no
        # entran en la firma. Solo los que pide el medio.
        for name in BUYER_FIELDS:
            value = order.buyer.get(name)
            if value:
                body[name] = value
        response = self._request("POST", "/create-order-tspay", json=body)
        if response.status_code in (200, 201):
            if not response.headers.get("content-type", "").startswith("text/html"):
                raise PaymentProviderError("Orden: la respuesta no es HTML")
            return CheckoutPage(html=response.text)
        detail = _error_message(response)
        # Manual §7.2: 400 = no se creo la orden (firma, cuerpo, medio, monto,
        # datos del comprador o pais). 401 y 500 son de configuracion; 502 es
        # EBANX sin redireccion, con la orden pendiente del lado de ellos.
        logger.warning("Tipster Page no creo la orden %s: HTTP %s %s",
                       order.reference, response.status_code, detail)
        if response.status_code == 400:
            raise CheckoutRejected(detail or "Orden rechazada")
        raise PaymentProviderError(f"Orden: HTTP {response.status_code}")

    # ---- aviso de pago (manual §9)

    def parse_event(self, body: bytes, headers: Mapping[str, str]) -> ProviderEvent:
        """Manual §9: `{paid_status, order_id, amount, nt_signature}`, firmado
        con §9.1 sobre el `amount` crudo. Nunca lanza.

        El aviso no trae un id propio; el manual §9.2 dice que la entrega es
        idempotente por resultado. El id del evento es la orden con su
        resultado (decidido el 2026-11-03).

        Un aviso con otro `paid_status` no es de pago: es la devolucion
        manual, que pasa la orden a `refund` (respuesta de Tipster Page,
        2026-11-06; el manual V2 no lo documenta). Se acepta sin mover nada,
        con firma valida o sin ella: la devolucion solo se registra
        (decidido el 2026-11-06), y la registra el admin a mano.
        """
        try:
            raw = _raw_json(body)
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return unverified_event(self.name, body, None)
        if not isinstance(raw, dict) or not isinstance(payload, dict):
            return unverified_event(self.name, body, None)
        if "event_type" in payload:
            return self._subscription_event(body, payload)
        paid_status = raw.get("paid_status")
        order_id = raw.get("order_id")
        amount = raw.get("amount")
        received = raw.get("nt_signature")
        if (
            # `raw` deja los numeros como texto (para firmar el monto como
            # llego): el tipo del estado se mira en el JSON leido.
            not isinstance(payload.get("paid_status"), str)
            or not isinstance(paid_status, str)
            or not paid_status
            or len(paid_status) > MAX_NOTICE_STATUS_LENGTH
            or not isinstance(order_id, str)
            or not order_id
            or len(order_id) > 200
        ):
            return unverified_event(self.name, body, payload)
        verified = (
            isinstance(amount, str)
            and isinstance(received, str)
            and hmac.compare_digest(
                notification_signature(self._secret_key, paid_status, order_id, amount).encode(),
                received.strip().lower().encode(),
            )
        )
        if paid_status not in NOTIFICATION_STATUSES:
            # Sin firma valida, el id va al espacio de los no verificados: un
            # aviso falsificado no ocupa el de uno autentico.
            event_id = (
                f"{self.name}:{order_id}:{paid_status}"
                if verified
                else unverified_event(self.name, body, payload).event_id
            )
            return ProviderEvent(
                event_id=event_id,
                event_type="order.notice",
                signature_verified=verified,
                transaction_id=None,
                status=paid_status,
                payload=payload,
                notice_only=True,
            )
        if not verified:
            return unverified_event(self.name, body, payload)
        return ProviderEvent(
            event_id=f"{self.name}:{order_id}:{paid_status}",
            event_type="order.notification",
            signature_verified=True,
            transaction_id=order_id,
            status=paid_status,
            payload=payload,
        )

    def _subscription_event(self, body: bytes, payload: dict[str, Any]) -> ProviderEvent:
        """Suscripciones §3: un aviso de una suscripcion, firmado sobre su JSON
        canonico (§3.3). Trae su propio `event_id`, el mismo en cada reintento.

        Solo dice que suscripcion mirar: el webhook reconsulta sus pagos. La
        devolucion (`REFUND_EVENT`) no mueve nada, como la de una orden.
        """
        verified = verified_notification(self._secret_key, body)
        if verified is None:
            return unverified_event(self.name, body, payload)
        event_id = verified.get("event_id")
        event_type = verified.get("event_type")
        subscription_id = verified.get("subscription_id")
        external_id = verified.get("external_id")
        if (
            not isinstance(event_id, str)
            or not 0 < len(event_id) <= 200
            or not isinstance(event_type, str)
            or not event_type
            or not isinstance(subscription_id, str)
            or not _is_uuid(subscription_id)
        ):
            return unverified_event(self.name, body, payload)
        data = verified.get("data")
        data = data if isinstance(data, dict) else {}
        status = data.get("paid_status") or data.get("status") or event_type
        return ProviderEvent(
            event_id=f"{self.name}:sub:{event_id}",
            event_type=event_type[:100],
            signature_verified=True,
            transaction_id=None,
            status=str(status)[:MAX_NOTICE_STATUS_LENGTH],
            payload=verified,
            notice_only=event_type == REFUND_EVENT,
            agreement_id=subscription_id,
            external_reference=(
                external_id if isinstance(external_id, str) and 0 < len(external_id) <= 255 else None
            ),
        )

    # ---- reconsulta (manual §10)

    def fetch_transaction(self, transaction_id: str) -> ProviderTransaction | None:
        """Reconsulta una orden o un pago de una suscripcion.

        Un pago de una suscripcion lleva el id que armamos al crearlo
        (`SUBSCRIPTION_TX_PREFIX`); cualquier otro es una orden.
        """
        if transaction_id.startswith(f"{SUBSCRIPTION_TX_PREFIX}:"):
            return self._fetch_subscription_payment(transaction_id)
        return self._fetch_order(transaction_id)

    def _fetch_order(self, transaction_id: str) -> ProviderTransaction | None:
        """Manual §10: `GET /order-status/{orderId}`. 404 = no la conoce.

        El monto llega en euros (respuesta de Tipster Page, pregunta 3). Se lee
        como `Decimal`; uno con mas de dos decimales no es un monto que
        pidieramos, y el pago queda en `error` para que alguien lo mire.
        """
        response = self._request("GET", f"/order-status/{quote(transaction_id, safe='')}")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise PaymentProviderError(f"Estado de la orden: HTTP {response.status_code}")
        try:
            data = json.loads(response.content, parse_float=Decimal)
        except (ValueError, UnicodeDecodeError) as exc:
            raise PaymentProviderError("Estado de la orden: respuesta inesperada") from exc
        if not isinstance(data, dict):
            raise PaymentProviderError("Estado de la orden: respuesta inesperada")
        raw_status = data.get("paid_order_status")
        product = data.get("product_id")
        status = STATUS_MAP.get(raw_status) if isinstance(raw_status, str) else None
        message = None if status == "approved" else f"Tipster Page: {raw_status}"
        if status is None:
            # Un estado que el manual no lista: no se mueve nada.
            logger.warning("Tipster Page: estado desconocido de la orden %s", transaction_id)
            status = "pending"
        cents = _euro_cents(data.get("amount"))
        if cents is None:
            status, cents = "error", 0
            message = "Tipster Page: monto ilegible en la reconsulta"
        return ProviderTransaction(
            id=transaction_id,
            reference=transaction_id,
            status=status,
            amount_cents=cents,
            currency=CURRENCY,
            status_message=message,
            product_code=product if isinstance(product, str) else None,
        )

    # ---- suscripciones (paso 5.3b)

    def recurring_method(self, country: str | None) -> PaymentMethodOption | None:
        """OpenAPI: `GET /subscriptions/payment-methods?country-code=`.

        El medio de Solidgate, si la pasarela lo ofrece en ese pais en el modo
        en que nosotros decidimos cuando cobrar (`MERCHANT_MANAGED`). Se guarda
        en memoria como el catalogo de las ordenes.
        """
        key = f"recurring:{country or ''}"
        now = time.monotonic()
        with self._lock:
            cached = self._catalog.get(key)
            if cached is not None and cached[0] > now:
                return cached[1][0] if cached[1] else None
        params = {"country-code": country} if country else None
        response = self._request("GET", "/subscriptions/payment-methods", params=params)
        if response.status_code != 200:
            raise PaymentProviderError(f"Medios de suscripcion: HTTP {response.status_code}")
        items = _json(response)
        if not isinstance(items, list):
            raise PaymentProviderError("Medios de suscripcion: respuesta inesperada")
        found = next(
            (m for m in (_recurring_method(item, country) for item in items) if m is not None), None
        )
        with self._lock:
            self._catalog[key] = (now + CATALOG_TTL_SECONDS, [found] if found else [])
        return found

    def start_recurring(self, order: RecurringOrder) -> RecurringStart:
        """OpenAPI: `POST /subscriptions`, accion `CREATE` (suscripciones §2).

        `external_id` es la referencia del pago del alta: unica por comercio
        (§2.6) y la que trae cada aviso. El primer cobro se hace en la pagina
        de Solidgate (`checkout_url`), por `amount`; los siguientes los pide
        `charge`. La respuesta sola no confirma ningun pago.
        """
        if order.currency != CURRENCY:
            raise CheckoutRejected("Tipster Page solo cobra en euros")
        periodicity = PERIODICITIES.get((order.interval, order.interval_count))
        if periodicity is None:
            raise CheckoutRejected("La duracion del plan no tiene periodicidad en Tipster Page")
        params: dict[str, Any] = {
            "idempotency_key": _idempotency_key("CREATE", order.reference),
            "product_id": order.product_code,
            "product_name": order.product_name,
            "amount": amount_number(order.amount_cents),
            "periodicity": periodicity,
            "external_id": order.reference,
            "email": order.email,
            "country": order.country,
            "language": order.language,
            "url_ok": order.url_ok,
            "url_ko": order.url_ko,
            "notification_url": order.notification_url,
            "terms_accepted": True,
        }
        if order.setup_only:
            # OpenAPI, `setup_only`: verifica y guarda la tarjeta por 0, sin
            # cobrar. Pasar a renovacion automatica con un periodo ya pagado.
            params["setup_only"] = True
        response = self._signed("POST", "/subscriptions", "CREATE", "", params)
        if response.status_code in (200, 201):
            data = _json(response)
            subscription_id = data.get("subscription_id") if isinstance(data, dict) else None
            checkout_url = data.get("checkout_url") if isinstance(data, dict) else None
            if (
                not isinstance(subscription_id, str)
                or not _is_uuid(subscription_id)
                or not isinstance(checkout_url, str)
                or not checkout_url.startswith("https://")
            ):
                raise PaymentProviderError("Alta de suscripcion: respuesta inesperada")
            return RecurringStart(
                checkout_url=checkout_url,
                transaction_id=_subscription_tx(subscription_id, INITIAL_PERIOD, order.reference),
                agreement_id=subscription_id,
            )
        # Sin el cuerpo de la peticion: lleva el correo del comprador.
        logger.warning(
            "Tipster Page no creo la suscripcion del pago %s: HTTP %s %s",
            order.reference,
            response.status_code,
            _error_message(response),
        )
        if response.status_code == 400:
            raise CheckoutRejected(_error_message(response) or "Suscripcion rechazada")
        raise PaymentProviderError(f"Alta de suscripcion: HTTP {response.status_code}")

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
        """OpenAPI: `POST /subscriptions/{id}/payments`, accion `CHARGE`.

        Un `period_id` por periodo, igual en todos sus intentos, y una clave de
        idempotencia por intento (sale de `reference`): suscripciones §4 y el
        OpenAPI ("after a retryable terminal failure, use a new key while
        keeping the same billing period, amount and period end"). La respuesta
        201 no confirma el pago: puede venir pendiente (§4).
        """
        if currency != CURRENCY:
            raise PaymentProviderError("Tipster Page solo cobra en euros")
        subscription_id = source.agreement_id
        if subscription_id is None or not _is_uuid(subscription_id) or not _is_uuid(source.id):
            raise PaymentProviderError("El medio de pago no es de una suscripcion de Tipster Page")
        params: dict[str, Any] = {
            "idempotency_key": _idempotency_key("CHARGE", reference),
            "period_id": period.key,
            "payment_method_id": source.id,
            "amount": amount_number(amount_cents),
            "period_end": period.end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        response = self._signed(
            "POST", f"/subscriptions/{subscription_id}/payments", "CHARGE", subscription_id, params
        )
        if response.status_code in (200, 201):
            transaction = _charge_transaction(_json_decimal(response), subscription_id, reference)
            if transaction is None:
                raise PaymentProviderError("Cobro: respuesta inesperada")
            return transaction
        # 400 y 409: el cobro no se hizo (periodo, limite de intentos, tarjeta
        # bloqueada...). Cuenta como un intento sin respuesta del proveedor.
        logger.warning(
            "Tipster Page no hizo el cobro %s: HTTP %s %s",
            reference,
            response.status_code,
            _error_message(response),
        )
        raise PaymentProviderError(f"Cobro: HTTP {response.status_code}")

    def _fetch_subscription_payment(self, transaction_id: str) -> ProviderTransaction | None:
        """El pago de una suscripcion: el del alta o un cobro.

        - El del alta: `GET /subscriptions/{id}` (que su `external_id` sea
          nuestra referencia) y el pago de periodo `initial` en
          `GET /subscriptions/{id}/payments`. Sin ese pago, si la suscripcion
          paso a `EXPIRED` el primer pago se rechazo (suscripciones §3.2); si
          no, sigue pendiente (el cliente no ha terminado de pagar).
        - Un cobro: `GET /subscriptions/{id}/payments/{paymentId}`.

        Visto en produccion el 2026-11-17 (alta de 1 EUR pagada): la suscripcion
        pasa de `PENDING_PAYMENT` a `ACTIVE` con `payment_status` `PAID`, y cada
        pago del listado trae `payment_id`, `order_id`, `cycle`, `period_id`,
        `amount`, `currency`, `status` en minusculas y `occurred_at`, sin
        `subscription_id`.
        """
        parts = transaction_id.split(":", 3)
        if len(parts) != 4 or not _is_uuid(parts[1]):
            return None
        _, subscription_id, payment_key, reference = parts
        if payment_key != INITIAL_PERIOD:
            if not _is_uuid(payment_key):
                return None
            response = self._request(
                "GET", f"/subscriptions/{subscription_id}/payments/{payment_key}"
            )
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                raise PaymentProviderError(f"Estado del cobro: HTTP {response.status_code}")
            return _charge_transaction(_json_decimal(response), subscription_id, reference)

        response = self._request("GET", f"/subscriptions/{subscription_id}")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise PaymentProviderError(f"Estado de la suscripcion: HTTP {response.status_code}")
        subscription = _json_decimal(response)
        if not isinstance(subscription, dict) or subscription.get("external_id") != reference:
            # No es la suscripcion de este pago: no se le cree nada.
            logger.error(
                "Tipster Page: la suscripcion %s no es la del pago %s", subscription_id, reference
            )
            return None
        response = self._request(
            "GET", f"/subscriptions/{subscription_id}/payments", params={"limit": 100}
        )
        if response.status_code != 200:
            raise PaymentProviderError(f"Cobros de la suscripcion: HTTP {response.status_code}")
        page = _json_decimal(response)
        items = page.get("items") if isinstance(page, dict) else None
        if not isinstance(items, list):
            raise PaymentProviderError("Cobros de la suscripcion: respuesta inesperada")
        initial = next(
            (i for i in items if isinstance(i, dict) and i.get("period_id") == INITIAL_PERIOD), None
        )
        amount = _euro_cents(subscription.get("amount")) or 0
        if initial is not None:
            found = _charge_transaction(initial, subscription_id, reference)
            if found is None:
                return None
            transaction = found
        elif str(subscription.get("status", "")).upper() == "EXPIRED":
            transaction = ProviderTransaction(
                id=transaction_id,
                reference=reference,
                status="declined",
                amount_cents=amount,
                currency=CURRENCY,
                status_message="Tipster Page: primer pago rechazado",
            )
        else:
            return ProviderTransaction(
                id=transaction_id,
                reference=reference,
                status="pending",
                amount_cents=amount,
                currency=CURRENCY,
            )
        if transaction.status != "approved":
            return transaction
        method_id = subscription.get("payment_method_id")
        if not isinstance(method_id, str) or not _is_uuid(method_id):
            # Pagado pero sin tarjeta guardada: no hay con que renovar. Sigue
            # pendiente para que alguien lo mire antes de conceder el periodo.
            logger.error("Tipster Page: la suscripcion %s no trae medio de pago", subscription_id)
            return ProviderTransaction(
                id=transaction_id,
                reference=reference,
                status="pending",
                amount_cents=transaction.amount_cents,
                currency=CURRENCY,
            )
        return ProviderTransaction(
            id=transaction_id,
            reference=reference,
            status="approved",
            amount_cents=transaction.amount_cents,
            currency=transaction.currency,
            saved_source=PaymentSource(id=method_id, type="CARD", agreement_id=subscription_id),
        )

    def card_change_url(self, source: PaymentSource, *, recovery: bool, reference: str) -> str:
        """OpenAPI: `POST /subscriptions/{id}/payment-method` (accion
        `PAYMENT_METHOD`) o, con un cobro rechazado, `.../payment-recovery`
        (`RECOVERY`). Un enlace privado de 48 h que verifica la tarjeta nueva
        por 0 sin cobrar ningun periodo. La misma `reference` devuelve el mismo
        enlace (idempotencia, suscripciones §2.6)."""
        subscription_id = source.agreement_id
        if subscription_id is None or not _is_uuid(subscription_id):
            raise PaymentProviderError("El medio de pago no es de una suscripcion de Tipster Page")
        action: Action = "RECOVERY" if recovery else "PAYMENT_METHOD"
        path = "payment-recovery" if recovery else "payment-method"
        params = {"idempotency_key": _idempotency_key(action, reference)}
        response = self._signed(
            "POST", f"/subscriptions/{subscription_id}/{path}", action, subscription_id, params
        )
        if response.status_code in (200, 201):
            data = _json(response)
            url = data.get("checkout_url") if isinstance(data, dict) else None
            if not isinstance(url, str) or not url.startswith("https://"):
                raise PaymentProviderError("Cambio de tarjeta: respuesta inesperada")
            return url
        logger.warning(
            "Tipster Page no abrio el cambio de tarjeta de %s: HTTP %s %s",
            subscription_id,
            response.status_code,
            _error_message(response),
        )
        raise PaymentProviderError(f"Cambio de tarjeta: HTTP {response.status_code}")

    def saved_source(self, agreement_id: str) -> PaymentSource | None:
        """OpenAPI: `GET /subscriptions/{id}`. La tarjeta que tiene guardada,
        si sirve para cobrar: con `payment_method_id`, sin un borrado en curso y
        con la suscripcion ni cancelada ni vencida."""
        if not _is_uuid(agreement_id):
            return None
        response = self._request("GET", f"/subscriptions/{agreement_id}")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise PaymentProviderError(f"Estado de la suscripcion: HTTP {response.status_code}")
        data = _json(response)
        if not isinstance(data, dict):
            raise PaymentProviderError("Estado de la suscripcion: respuesta inesperada")
        method_id = data.get("payment_method_id")
        if (
            not isinstance(method_id, str)
            or not _is_uuid(method_id)
            or data.get("payment_method_deletion") is not None
            or str(data.get("status", "")).upper() in ("CANCELLED", "EXPIRED")
        ):
            return None
        return PaymentSource(id=method_id, type="CARD", agreement_id=agreement_id)

    def delete_saved_source(self, source: PaymentSource, *, reference: str) -> None:
        """OpenAPI: `DELETE /subscriptions/{id}/payment-method`, accion
        `DELETE_PAYMENT_METHOD`, con `scope: SUBSCRIPTION`: borra el token de
        esta suscripcion y la cancela, sin tocar otras ni pedir la revocacion
        al proveedor. 200 lo confirma; 202 es un resultado incierto que se
        repite con la misma clave; 404, que ya no existe."""
        subscription_id = source.agreement_id
        if subscription_id is None or not _is_uuid(subscription_id) or not _is_uuid(source.id):
            raise PaymentProviderError("El medio de pago no es de una suscripcion de Tipster Page")
        params = {
            "idempotency_key": _idempotency_key("DELETE_PAYMENT_METHOD", reference),
            "payment_method_id": source.id,
            "scope": "SUBSCRIPTION",
        }
        response = self._signed(
            "DELETE",
            f"/subscriptions/{subscription_id}/payment-method",
            "DELETE_PAYMENT_METHOD",
            subscription_id,
            params,
        )
        if response.status_code in (200, 404):
            return
        logger.warning(
            "Tipster Page no confirmo el borrado de la tarjeta de %s: HTTP %s %s",
            subscription_id,
            response.status_code,
            _error_message(response),
        )
        raise PaymentProviderError(f"Borrado de la tarjeta: HTTP {response.status_code}")

    def _signed(
        self, method: str, path: str, action: Action, resource: str, params: dict[str, Any]
    ) -> httpx.Response:
        body = signed_body(self._secret_key, self._merchant, action, resource, params)
        return self._request(method, path, json=body)

    # ---- HTTP

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            # Sin el cuerpo ni las cabeceras: llevan las llaves y los datos del comprador.
            raise PaymentProviderError(f"Tipster Page no respondio ({type(exc).__name__})") from None


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _idempotency_key(action: str, reference: str) -> str:
    return str(uuid.uuid5(_IDEMPOTENCY_NAMESPACE, f"{action}:{reference}"))


def _subscription_tx(subscription_id: str, payment_key: str, reference: str) -> str:
    return f"{SUBSCRIPTION_TX_PREFIX}:{subscription_id}:{payment_key}:{reference}"


def _json_decimal(response: httpx.Response) -> Any:
    """El JSON con los montos como `Decimal`, sin pasar por `float`."""
    try:
        return json.loads(response.content, parse_float=Decimal)
    except (ValueError, UnicodeDecodeError) as exc:
        raise PaymentProviderError("Respuesta que no es JSON") from exc


def _charge_transaction(
    data: Any, subscription_id: str, reference: str
) -> ProviderTransaction | None:
    """Un cobro de una suscripcion (OpenAPI, `TspaySubscriptionChargeResult`).

    None si no es el cobro de esa suscripcion o no se puede leer.
    """
    if not isinstance(data, dict):
        return None
    payment_id = data.get("payment_id")
    if not isinstance(payment_id, str) or not _is_uuid(payment_id):
        return None
    owner = data.get("subscription_id")
    if owner is not None and owner != subscription_id:
        logger.error(
            "Tipster Page: el cobro %s no es de la suscripcion %s", payment_id, subscription_id
        )
        return None
    key = INITIAL_PERIOD if data.get("period_id") == INITIAL_PERIOD else payment_id
    raw_status = data.get("status")
    # El cobro y su consulta lo traen en mayusculas (`PAID`), como el OpenAPI;
    # el listado de cobros de la suscripcion, en minusculas (`paid`, visto en
    # produccion el 2026-11-17).
    status = CHARGE_STATUS_MAP.get(raw_status.upper()) if isinstance(raw_status, str) else None
    error_code = data.get("error_code")
    message = None
    if status is None:
        logger.warning("Tipster Page: estado desconocido del cobro %s", payment_id)
        status = "pending"
    elif status != "approved":
        message = f"Tipster Page: {raw_status}" + (
            f" ({str(error_code)[:20]})" if error_code else ""
        )
    cents = _euro_cents(data.get("amount"))
    if cents is None or data.get("currency", CURRENCY) != CURRENCY:
        status, cents = "error", 0
        message = "Tipster Page: monto ilegible en el cobro"
    retry = data.get("retry_allowed")
    auth_url = data.get("authentication_url")
    return ProviderTransaction(
        id=_subscription_tx(subscription_id, key, reference),
        reference=reference,
        status=status,
        amount_cents=cents,
        currency=CURRENCY,
        status_message=message,
        retry_allowed=retry if isinstance(retry, bool) else None,
        authentication_url=(
            auth_url
            if data.get("authentication_required") is True
            and isinstance(auth_url, str)
            and auth_url.startswith("https://")
            else None
        ),
    )


def _recurring_method(item: Any, country: str | None) -> PaymentMethodOption | None:
    """El medio de Solidgate del catalogo de suscripciones, si sirve: en euros,
    con los cobros a cargo nuestro y disponible en el pais."""
    if not isinstance(item, dict) or item.get("key") != RECURRING_METHOD:
        return None
    capabilities = item.get("capabilities") or {}
    low = _euro_cents(_decimal(item.get("priceMin")))
    high = _euro_cents(_decimal(item.get("priceMax")))
    countries = item.get("countries") or []
    if (
        item.get("currency") != CURRENCY
        or item.get("billing_mode") != "MERCHANT_MANAGED"
        or not isinstance(capabilities, dict)
        or capabilities.get("merchant_initiated_charges") is not True
        or low is None
        or high is None
        or not isinstance(countries, list)
    ):
        return None
    codes = tuple(c.upper() for c in countries if isinstance(c, str))
    if codes and (country is None or country.upper() not in codes):
        return None
    return PaymentMethodOption(
        key=RECURRING_METHOD,
        name="Tarjeta de crédito/débito",
        logo_url=None,
        min_cents=low,
        max_cents=high,
        currency=CURRENCY,
        countries=codes,
    )


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise PaymentProviderError("Respuesta que no es JSON") from exc


def _error_message(response: httpx.Response) -> str:
    """El `message` de un error de Tipster Page (OpenAPI, `ErrorResponse`)."""
    try:
        data = response.json()
    except ValueError:
        return ""
    message = data.get("message") if isinstance(data, dict) else None
    if isinstance(message, list):
        message = "; ".join(str(m) for m in message)
    return str(message)[:300] if message else ""


def _method(item: Any) -> PaymentMethodOption | None:
    """Un medio del catalogo (manual §5, OpenAPI `PaymentMethod`). Uno mal
    formado, de cripto (`EXCLUDED_METHODS`) o que pide un dato que no sabemos
    pedir, no se ofrece."""
    if not isinstance(item, dict):
        return None
    key, name = item.get("key"), item.get("name")
    low, high = _euro_cents(_decimal(item.get("priceMin"))), _euro_cents(_decimal(item.get("priceMax")))
    countries, fields = item.get("countries") or [], item.get("fields") or []
    if (
        not isinstance(key, str)
        or not key
        or not isinstance(name, str)
        or low is None
        or high is None
        or not isinstance(countries, list)
        or not isinstance(fields, list)
    ):
        return None
    if key in EXCLUDED_METHODS:
        return None
    known: list[BuyerField] = []
    for wanted in fields:
        match = next((f for f in BUYER_FIELDS if f == wanted), None)
        if match is None:
            logger.warning("Tipster Page: el medio %s pide un dato desconocido", key)
            return None
        known.append(match)
    logo = item.get("logoUrl")
    return PaymentMethodOption(
        key=key,
        name=DISPLAY_NAMES.get(key, name),
        logo_url=logo if isinstance(logo, str) and logo.startswith("https://") else None,
        min_cents=low,
        max_cents=high,
        currency=CURRENCY,
        countries=tuple(c.upper() for c in countries if isinstance(c, str)),
        fields=tuple(known),
        usd_outside_eurozone=key in STRIPE_METHODS,
    )


def _decimal(value: Any) -> Decimal | None:
    """Los numeros del catalogo llegan como `int` o `float` de `response.json()`."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(value))


# ---------------------------------------------------------------- arranque


def from_settings(settings: Settings) -> TipsterPageProvider:
    """El proveedor con las llaves del entorno. Si faltan o la URL base no es
    una de las dos del manual §3, la API no arranca y el error dice que
    variable, nunca su valor."""
    values = {
        "TSPAY_API_BASE_URL": settings.tspay_api_base_url.strip(),
        "TSPAY_MERCHANT_CODE": settings.tspay_merchant_code.strip(),
        "TSPAY_AUTH_BEARER": settings.tspay_auth_bearer.strip(),
        # El secreto no se recorta: puede terminar en un caracter que importe.
        "TSPAY_SECRET_KEY": settings.tspay_secret_key,
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ProviderMisconfigured(
            f"PAYMENT_PROVIDER=tipsterpage sin {', '.join(missing)}"
        )
    base_url = values["TSPAY_API_BASE_URL"].rstrip("/")
    if base_url not in (SANDBOX_BASE_URL, PRODUCTION_BASE_URL):
        raise ProviderMisconfigured(
            "TSPAY_API_BASE_URL no es la URL del sandbox ni la de produccion de Tipster Page"
        )
    return TipsterPageProvider(
        base_url=base_url,
        merchant_code=values["TSPAY_MERCHANT_CODE"],
        auth_bearer=values["TSPAY_AUTH_BEARER"],
        secret_key=values["TSPAY_SECRET_KEY"],
    )


def has_production_keys(settings: Settings) -> bool:
    """Las llaves del entorno son las de produccion de Tipster Page."""
    return settings.tspay_api_base_url.strip().rstrip("/") == PRODUCTION_BASE_URL


def check_startup(settings: Settings) -> None:
    """Las protecciones de arranque que salieron con Wompi (§3.18) y vuelven
    aqui: con llaves de produccion, una configuracion de desarrollo no arranca.

    - `PAYMENT_PROVIDER=fake` daria acceso sin cobrar.
    - `EMAIL_BACKEND=file` deja los correos en disco en vez de enviarlos.
    - Con `tipsterpage`, el manual §2 exige HTTPS en `url_ok`, `url_ko` y
      `notification_url`: la API y el frontend publicos tienen que ir por HTTPS.

    En cualquier ambiente, con `tipsterpage` esas dos URL tienen que ser
    absolutas: sin el esquema (`api.sebasanalisis.com`), Tipster Page rechaza
    cada orden con un 400 "Invalid request data" (visto en el VPS el
    2026-11-05), y la API arrancaba igual.
    """
    if settings.payment_provider == "tipsterpage":
        for name, url in (
            ("API_PUBLIC_URL", settings.api_public_url),
            ("FRONTEND_BASE_URL", settings.frontend_base_url),
        ):
            parts = urlsplit(url.strip())
            if parts.scheme not in ("http", "https") or not parts.netloc:
                raise ProviderMisconfigured(
                    f"{name} tiene que ser una URL completa, con https:// (vale {url!r})"
                )
    if not has_production_keys(settings):
        return
    if settings.payment_provider == "fake":
        raise ProviderMisconfigured(
            "PAYMENT_PROVIDER=fake no se usa con llaves de produccion de Tipster Page"
        )
    if settings.email_backend == "file":
        raise ProviderMisconfigured(
            "EMAIL_BACKEND=file no se usa con llaves de produccion de Tipster Page"
        )
    if settings.payment_provider == "tipsterpage":
        for name, url in (
            ("API_PUBLIC_URL", settings.api_public_url),
            ("FRONTEND_BASE_URL", settings.frontend_base_url),
        ):
            if not url.startswith("https://"):
                raise ProviderMisconfigured(f"{name} debe ir por HTTPS con Tipster Page en produccion")
