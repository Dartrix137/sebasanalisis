"""Tipster Page: integracion V2 sin landing (Fase 5, paso 5.3).

Fuente de todo lo que sigue, leida el 2026-11-04:

- El manual oficial "Documentacion de integracion -- Plataforma de pago
  Tipsterpage tsPay v2", v2.0 del 2026-10-29
  (`docs/docs tipsterpage/MANUAL_INTEGRACION_API_PAGOS_TSPAY_V2_NO_LANDING.pdf`,
  fuera del repositorio). Las secciones se citan como "manual §N".
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
siempre en euros, con dos decimales (manual §7, `amount`). No tiene cobros
recurrentes ("en desarrollo", 2026-11-03): no tokeniza.

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
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings
from app.payments.base import (
    BUYER_FIELDS,
    BuyerField,
    CheckoutOrder,
    CheckoutPage,
    CheckoutRejected,
    PaymentMethodOption,
    PaymentProviderError,
    PaymentSource,
    PaymentSourceType,
    PaymentsUnavailable,
    ProviderEvent,
    ProviderMisconfigured,
    ProviderTransaction,
    TokenizerInfo,
    TransactionStatus,
    unverified_event,
)

logger = logging.getLogger(__name__)

NAME = "tipsterpage"
CURRENCY = "EUR"

# Manual §3: las dos URL base, con el prefijo de version incluido.
SANDBOX_BASE_URL = "https://sandboxv2.ttpgpay.com/tspayv2"
PRODUCTION_BASE_URL = "https://paymentsv2.ttpgpay.com/tspayv2"

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

#: El catalogo cambia poco; con esto no se le pide en cada pantalla.
CATALOG_TTL_SECONDS = 300.0

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
        """
        try:
            raw = _raw_json(body)
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return unverified_event(self.name, body, None)
        if not isinstance(raw, dict) or not isinstance(payload, dict):
            return unverified_event(self.name, body, None)
        paid_status = raw.get("paid_status")
        order_id = raw.get("order_id")
        amount = raw.get("amount")
        received = raw.get("nt_signature")
        if (
            paid_status not in NOTIFICATION_STATUSES
            or not isinstance(order_id, str)
            or not order_id
            or len(order_id) > 200
            or not isinstance(amount, str)
            or not isinstance(received, str)
        ):
            return unverified_event(self.name, body, payload)
        expected = notification_signature(self._secret_key, paid_status, order_id, amount)
        if not hmac.compare_digest(expected.encode(), received.strip().lower().encode()):
            return unverified_event(self.name, body, payload)
        return ProviderEvent(
            event_id=f"{self.name}:{order_id}:{paid_status}",
            event_type="order.notification",
            signature_verified=True,
            transaction_id=order_id,
            status=paid_status,
            payload=payload,
        )

    # ---- reconsulta (manual §10)

    def fetch_transaction(self, transaction_id: str) -> ProviderTransaction | None:
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

    # ---- lo que no tiene

    def tokenizer(self) -> TokenizerInfo | None:
        # Sin cobros recurrentes: no se ofrece la renovacion automatica.
        return None

    def create_payment_source(
        self, *, source_type: PaymentSourceType, token: str, customer_email: str
    ) -> PaymentSource:
        raise PaymentsUnavailable("Tipster Page no guarda medios de pago")

    def charge(
        self,
        *,
        reference: str,
        amount_cents: int,
        currency: str,
        customer_email: str,
        source: PaymentSource,
    ) -> ProviderTransaction:
        raise PaymentsUnavailable("Tipster Page no hace cobros recurrentes")

    # ---- HTTP

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            # Sin el cuerpo ni las cabeceras: llevan las llaves y los datos del comprador.
            raise PaymentProviderError(f"Tipster Page no respondio ({type(exc).__name__})") from None


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
    formado, o que pide un dato que no sabemos pedir, no se ofrece."""
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
        name=name,
        logo_url=logo if isinstance(logo, str) and logo.startswith("https://") else None,
        min_cents=low,
        max_cents=high,
        currency=CURRENCY,
        countries=tuple(c.upper() for c in countries if isinstance(c, str)),
        fields=tuple(known),
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
    """
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
