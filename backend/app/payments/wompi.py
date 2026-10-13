"""Wompi como proveedor de pagos (docs/PLATAFORMA_COMPLETA.md §3).

Todo lo que este modulo sabe de Wompi salio de su documentacion oficial,
consultada el 2026-10-13. Antes de cambiar una firma o un endpoint se vuelve a
leer la pagina que corresponde; nunca de memoria (CLAUDE.md, "Pagos con Wompi").

- Ambientes y llaves: https://docs.wompi.co/docs/colombia/ambientes-y-llaves/
  Sandbox `https://sandbox.wompi.co/v1`, produccion `https://production.wompi.co/v1`.
  Prefijos: `pub_test_`/`pub_prod_`, `prv_test_`/`prv_prod_`,
  `test_events_`/`prod_events_`, `test_integrity_`/`prod_integrity_`.
- Web Checkout y firma de integridad:
  https://docs.wompi.co/docs/colombia/widget-checkout-web/
- Eventos (webhooks) y su checksum: https://docs.wompi.co/docs/colombia/eventos/
- Consulta de una transaccion:
  https://docs.wompi.co/docs/colombia/seguimiento-de-transacciones/

El pago manual usa el Web Checkout: el cliente paga en la pagina de Wompi con
cualquier medio que el comercio tenga habilitado en su panel. Por aqui no pasa
ningun dato de tarjeta ni de cuenta.
"""

import hashlib
import hmac
import json
import logging
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlencode

import httpx

from app.core.config import Settings
from app.payments.base import (
    PaymentProviderError,
    ProviderEvent,
    ProviderTransaction,
    TransactionStatus,
    unverified_event,
)

logger = logging.getLogger(__name__)

WompiEnvironment = Literal["sandbox", "production"]

# El Web Checkout es una sola URL para los dos ambientes: el ambiente lo decide
# la llave publica (documentacion de "Widget & Checkout Web").
CHECKOUT_URL = "https://checkout.wompi.co/p/"

API_BASE_URLS: dict[WompiEnvironment, str] = {
    "sandbox": "https://sandbox.wompi.co/v1",
    "production": "https://production.wompi.co/v1",
}

# (prefijo de sandbox, prefijo de produccion) de cada llave.
_KEY_PREFIXES: dict[str, tuple[str, str]] = {
    "wompi_public_key": ("pub_test_", "pub_prod_"),
    "wompi_private_key": ("prv_test_", "prv_prod_"),
    "wompi_events_secret": ("test_events_", "prod_events_"),
    "wompi_integrity_secret": ("test_integrity_", "prod_integrity_"),
}

# Estados de una transaccion segun la documentacion: PENDING mientras se
# procesa; APPROVED, DECLINED, VOIDED (solo tarjeta) y ERROR son finales.
_STATUSES: dict[str, TransactionStatus] = {
    "PENDING": "pending",
    "APPROVED": "approved",
    "DECLINED": "declined",
    "VOIDED": "voided",
    "ERROR": "error",
}

EVENT_CHECKSUM_HEADER = "x-event-checksum"
HTTP_TIMEOUT_SECONDS = 10.0


def wompi_keys_present(settings: Settings) -> bool:
    """Hay algo configurado. Con una sola llave puesta ya se exige el resto."""
    return any(getattr(settings, name) for name in _KEY_PREFIXES)


def has_production_keys(settings: Settings) -> bool:
    return any(
        getattr(settings, name).startswith(prod) for name, (_, prod) in _KEY_PREFIXES.items()
    )


def key_environment(settings: Settings) -> WompiEnvironment:
    """El ambiente de las llaves. Falla si falta alguna o si estan mezcladas.

    Un despliegue con llaves de sandbox y de produccion revueltas no arranca:
    es preferible a cobrar contra el ambiente equivocado (§12).
    """
    found: set[WompiEnvironment] = set()
    for name, (test, prod) in _KEY_PREFIXES.items():
        value = getattr(settings, name)
        variable = name.upper()
        if not value:
            raise ValueError(f"Falta {variable}: Wompi necesita las cuatro llaves")
        if value.startswith(test):
            found.add("sandbox")
        elif value.startswith(prod):
            found.add("production")
        else:
            raise ValueError(f"{variable} no tiene el prefijo de una llave de Wompi")
    if len(found) != 1:
        raise ValueError("Las llaves de Wompi mezclan sandbox y produccion")
    environment = found.pop()

    base_url = settings.wompi_api_base_url.rstrip("/")
    if base_url and base_url != API_BASE_URLS[environment]:
        raise ValueError(
            f"WOMPI_API_BASE_URL no corresponde a las llaves, que son de {environment}"
        )
    return environment


def integrity_signature(
    reference: str, amount_cents: int, currency: str, integrity_secret: str
) -> str:
    """Firma de integridad de una transaccion del Web Checkout.

    Documentacion ("Widget & Checkout Web", consultada el 2026-10-13): SHA-256,
    en hexadecimal, de la concatenacion sin separadores de la referencia, el
    monto en centavos, la moneda y el secreto de integridad, en ese orden. (Con
    `expiration-time` la fecha va antes del secreto; aqui no se usa.)
    """
    chain = f"{reference}{amount_cents}{currency}{integrity_secret}"
    return hashlib.sha256(chain.encode("utf-8")).hexdigest()


def _lookup(data: Any, path: str) -> str | None:
    """El valor de `transaction.id` dentro de `data`, como texto."""
    value = data
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    # Solo texto y enteros: son los unicos tipos que la documentacion muestra en
    # la firma. Con cualquier otro no se adivina como lo escribio Wompi.
    if isinstance(value, bool) or not isinstance(value, str | int):
        return None
    return str(value)


def event_checksum(payload: Mapping[str, Any], events_secret: str) -> str | None:
    """El checksum que deberia traer un evento, o None si no se puede calcular.

    Documentacion ("Eventos", consultada el 2026-10-13):
    1. Se concatenan los valores de los campos que el propio evento lista en
       `signature.properties`, buscados dentro de `data` y en ese orden. La
       lista no es fija: se lee del evento.
    2. Se agrega el `timestamp` del evento.
    3. Se agrega el secreto de eventos del comercio.
    4. SHA-256 de esa cadena, en hexadecimal.
    """
    signature = payload.get("signature")
    timestamp = payload.get("timestamp")
    if not isinstance(signature, dict) or isinstance(timestamp, bool):
        return None
    if not isinstance(timestamp, int | str):
        return None
    properties = signature.get("properties")
    if not isinstance(properties, list) or not properties:
        return None
    chain = ""
    for prop in properties:
        if not isinstance(prop, str):
            return None
        value = _lookup(payload.get("data"), prop)
        if value is None:
            return None
        chain += value
    chain += f"{timestamp}{events_secret}"
    return hashlib.sha256(chain.encode("utf-8")).hexdigest()


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.strip().lower().encode(), b.strip().lower().encode())


class WompiProvider:
    name = "wompi"
    enabled = True

    def __init__(
        self,
        *,
        public_key: str,
        private_key: str,
        events_secret: str,
        integrity_secret: str,
        api_base_url: str,
        environment: WompiEnvironment,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.public_key = public_key
        self._private_key = private_key
        self._events_secret = events_secret
        self._integrity_secret = integrity_secret
        self.api_base_url = api_base_url.rstrip("/")
        self.environment = environment
        # Los tests pasan un transporte que responde sin salir a la red.
        self._transport = transport

    @classmethod
    def from_settings(cls, settings: Settings) -> "WompiProvider":
        environment = key_environment(settings)
        return cls(
            public_key=settings.wompi_public_key,
            private_key=settings.wompi_private_key,
            events_secret=settings.wompi_events_secret,
            integrity_secret=settings.wompi_integrity_secret,
            api_base_url=API_BASE_URLS[environment],
            environment=environment,
        )

    def describe(self) -> str:
        return f"Wompi, ambiente {self.environment} ({self.api_base_url})"

    def checkout_url(
        self,
        *,
        reference: str,
        amount_cents: int,
        currency: str,
        redirect_url: str,
        customer_email: str,
    ) -> str:
        # Los mismos campos del formulario GET de la documentacion. El navegador
        # tambien codifica los dos puntos del nombre al enviarlo.
        params = {
            "public-key": self.public_key,
            "currency": currency,
            "amount-in-cents": str(amount_cents),
            "reference": reference,
            "signature:integrity": integrity_signature(
                reference, amount_cents, currency, self._integrity_secret
            ),
            "redirect-url": redirect_url,
            "customer-data:email": customer_email,
        }
        return f"{CHECKOUT_URL}?{urlencode(params)}"

    def parse_event(self, body: bytes, headers: Mapping[str, str]) -> ProviderEvent:
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            payload = None
        if not isinstance(payload, dict):
            return unverified_event(self.name, body, None)

        expected = event_checksum(payload, self._events_secret)
        signature = payload.get("signature")
        received = signature.get("checksum") if isinstance(signature, dict) else None
        # El checksum llega en el cuerpo y en la cabecera `X-Event-Checksum`.
        # Si viene la cabecera, tambien tiene que coincidir.
        header = next(
            (v for k, v in headers.items() if k.lower() == EVENT_CHECKSUM_HEADER), None
        )
        valid = (
            expected is not None
            and isinstance(received, str)
            and _same(expected, received)
            and (header is None or _same(expected, header))
        )
        if not valid or expected is None:
            return unverified_event(self.name, body, payload)

        event_type = payload.get("event")
        data = payload.get("data")
        transaction = data.get("transaction") if isinstance(data, dict) else None
        transaction = transaction if isinstance(transaction, dict) else {}
        transaction_id = transaction.get("id")
        status = transaction.get("status")
        return ProviderEvent(
            # Wompi no manda un id de evento. El checksum sale de la transaccion,
            # su estado y el `timestamp`, asi que un reintento del mismo evento
            # trae el mismo y dos eventos distintos no.
            event_id=f"{self.name}:{expected}",
            event_type=event_type if isinstance(event_type, str) else "unknown",
            signature_verified=True,
            transaction_id=transaction_id if isinstance(transaction_id, str) else None,
            status=status if isinstance(status, str) else "unknown",
            payload=payload,
        )

    def fetch_transaction(self, transaction_id: str) -> ProviderTransaction | None:
        # GET /v1/transactions/{id} con la llave privada como Bearer: sin ella
        # (o con la publica) Wompi responde 404.
        try:
            with httpx.Client(transport=self._transport, timeout=HTTP_TIMEOUT_SECONDS) as client:
                response = client.get(
                    f"{self.api_base_url}/transactions/{transaction_id}",
                    headers={"Authorization": f"Bearer {self._private_key}"},
                )
        except httpx.HTTPError as exc:
            raise PaymentProviderError(f"Wompi no respondio: {type(exc).__name__}") from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise PaymentProviderError(f"Wompi respondio {response.status_code}")
        try:
            data = response.json()["data"]
            status = _STATUSES[data["status"]]
            amount = data["amount_in_cents"]
            if isinstance(amount, bool) or not isinstance(amount, int):
                raise TypeError("amount_in_cents no es un entero")
            message = data.get("status_message")
            return ProviderTransaction(
                id=str(data["id"]),
                reference=str(data["reference"]),
                status=status,
                amount_cents=amount,
                currency=str(data["currency"]),
                status_message=message if isinstance(message, str) else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PaymentProviderError("Respuesta de Wompi que no se entiende") from exc
