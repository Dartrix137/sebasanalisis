"""Firma de las suscripciones de Tipster Page (renovacion automatica con Solidgate).

Fuente, leida el 2026-11-17, nunca de memoria (CLAUDE.md, "Pagos: reglas no
negociables"):

- `tspay-subscriptions.md`, el documento que Tipster Page mando ese dia para
  completar su OpenAPI (`docs/docs tipsterpage/`, fuera del repositorio). Se
  cita como "suscripciones §N".
- Su OpenAPI (`https://apiekans.tipster.page/tspayv2/docs`, con usuario y
  contrasena), rutas `/tspayv2/subscriptions...`.

No es la firma de las ordenes (`tipsterpage.order_signature`), que concatena
campos en un orden fijo. Aqui se firma un JSON canonico:

- una peticion que cambia algo firma `{merchant, action, resource, parameters}`
  (suscripciones §2.1), con `parameters` = el cuerpo sin `tspay_signature`;
- un aviso a `notification_url` firma su cuerpo sin `nt_signature`, sin
  envoltorio (suscripciones §3.3).

Las dos con `hex(HMAC-SHA256(clave secreta, JSON canonico))` y la misma clave
secreta de las ordenes. Python puro: sin red ni base.
"""

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any, Literal

#: Suscripciones §2.1: la `action` de cada operacion firmada.
Action = Literal[
    "CREATE",
    "UPDATE",
    "CHARGE",
    "CANCEL",
    "RECOVERY",
    "RESUME",
    "PAYMENT_METHOD",
    "DELETE_PAYMENT_METHOD",
]


def amount_number(amount_cents: int) -> int | float:
    """Un monto en centavos como el numero JSON que firma el servidor.

    Suscripciones §2.2, regla 4: la forma mas corta, `9.9` y no `9.90`, `32` y
    no `32.0`. Un monto sin centavos va como `int`: en Python un `float` entero
    se escribe `32.0` (suscripciones §2.4). Con centavos, `n / 100` es el
    `float` mas cercano a ese decimal, y `json.dumps` lo escribe con los
    digitos minimos, como `JSON.stringify`.
    """
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
        raise TypeError("El monto va en centavos, como entero")
    if amount_cents <= 0:
        raise ValueError("El monto debe ser positivo")
    units, cents = divmod(amount_cents, 100)
    return units if cents == 0 else amount_cents / 100


def canonical_json(value: Any) -> str:
    """Suscripciones §2.2: el texto que se firma.

    Claves ordenadas en todos los niveles, sin espacios, sin escapar `/` ni lo
    que no es ASCII, y numeros en su forma mas corta. Es su implementacion de
    referencia en Python (§2.4), mas `allow_nan=False`: un `NaN` no es JSON y
    JavaScript no lo firmaria igual.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _hmac_hex(secret_key: str, text: str) -> str:
    return hmac.new(secret_key.encode(), text.encode("utf-8"), hashlib.sha256).hexdigest()


def request_signature(
    secret_key: str,
    merchant: str,
    action: Action,
    resource: str,
    parameters: Mapping[str, Any],
) -> str:
    """Suscripciones §2.3: el `tspay_signature` de una peticion.

    `merchant` es el de la cabecera `X-TSPAY-USER`, sin espacios en los bordes;
    `resource` es `""` en el alta y el id de la suscripcion en lo demas;
    `parameters` es el cuerpo que se envia, sin `tspay_signature`. Un campo
    opcional que no se envia tampoco entra.
    """
    if "tspay_signature" in parameters:
        raise ValueError("La firma no entra en lo que se firma")
    text = canonical_json(
        {
            "merchant": merchant.strip(),
            "action": action,
            "resource": resource,
            "parameters": dict(parameters),
        }
    )
    return _hmac_hex(secret_key, text)


def signed_body(
    secret_key: str,
    merchant: str,
    action: Action,
    resource: str,
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    """El cuerpo listo para enviar: los parametros con su `tspay_signature`."""
    signature = request_signature(secret_key, merchant, action, resource, parameters)
    return {**parameters, "tspay_signature": signature}


def verified_notification(secret_key: str, body: bytes) -> dict[str, Any] | None:
    """Suscripciones §3.3: el aviso leido, si su `nt_signature` es valida.

    No se firma el texto recibido: el orden de sus claves no es el canonico.
    Se lee el JSON, se quita `nt_signature`, se vuelve a escribir en forma
    canonica y se compara en tiempo constante. Los numeros se leen como los
    lee el servidor (`float` e `int`), para escribirlos igual que el.

    Devuelve el aviso sin `nt_signature`, o None si no es JSON, no trae firma
    o la firma no coincide. Nunca lanza.
    """
    try:
        payload = json.loads(body, parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    signature = payload.pop("nt_signature", None)
    if not isinstance(signature, str):
        return None
    try:
        expected = _hmac_hex(secret_key, canonical_json(payload))
    except ValueError:
        return None
    # En bytes: con texto, `compare_digest` lanza si llega algo que no es ASCII.
    if not hmac.compare_digest(expected.encode(), signature.encode("utf-8")):
        return None
    return payload


def _reject_constant(name: str) -> Any:
    """`NaN` e `Infinity` no son JSON: un aviso que los traiga no se verifica."""
    raise ValueError(f"Constante no valida en JSON: {name}")
