"""Monitoreo de errores (docs/PLATAFORMA_COMPLETA.md §13.6).

La API usa `sentry-sdk` apuntando a GlitchTip, que habla el mismo protocolo y
corre en el VPS: no se envia nada a un tercero. Sin `SENTRY_DSN` queda
desactivado (desarrollo, tests y CI).

Lo que no sale de la aplicacion, aunque haya un error: cabeceras de
autenticacion, cuerpos de `/auth/*` y `/billing/*`, y el cuerpo crudo de los
webhooks. Ni contrasenas, ni tokens, ni referencias de pago llegan al monitoreo.
"""

from typing import Any
from urllib.parse import urlsplit

import sentry_sdk

SENSITIVE_HEADERS = frozenset({"authorization", "cookie", "set-cookie", "x-api-key"})
# Rutas cuyo cuerpo nunca se envia: credenciales, datos de pago y webhooks.
SENSITIVE_PATH_PREFIXES = ("/auth", "/billing", "/webhooks")
FILTERED = "[filtrado]"


def _is_sensitive_path(url: str) -> bool:
    path = urlsplit(url).path
    return any(path == p or path.startswith(p + "/") for p in SENSITIVE_PATH_PREFIXES)


def scrub_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """`before_send`: quita los datos sensibles de un evento antes de enviarlo.

    Funcion pura sobre el diccionario del evento, para poder probarla sin red.
    """
    request = event.get("request")
    if not isinstance(request, dict):
        return event

    headers = request.get("headers")
    if isinstance(headers, dict):
        request["headers"] = {
            name: FILTERED if name.lower() in SENSITIVE_HEADERS else value
            for name, value in headers.items()
        }

    request.pop("cookies", None)

    if _is_sensitive_path(str(request.get("url", ""))):
        if "data" in request:
            request["data"] = FILTERED
        # Los tokens de un solo uso pueden viajar en la URL de un enlace.
        if request.get("query_string"):
            request["query_string"] = FILTERED

    return event


def init_monitoring(dsn: str) -> bool:
    """Activa el monitoreo si hay DSN. Devuelve si quedo activo."""
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        send_default_pii=False,
        # Las variables locales de un traceback pueden traer una contrasena o
        # un token tal como llegaron al endpoint.
        include_local_variables=False,
        before_send=scrub_event,  # type: ignore[arg-type]
        # Solo errores: sin trazas de rendimiento.
        traces_sample_rate=0.0,
    )
    return True
