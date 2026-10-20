"""Cabeceras de seguridad de la API (paso 9 de la Fase 4).

La API responde JSON a un frontend en otro dominio: nada de lo que devuelve se
tiene que poder mostrar en un marco, interpretar como otro tipo de contenido ni
mandar la pagina de origen a terceros. HSTS le dice al navegador que este
dominio va siempre por HTTPS (Traefik ya redirige `http://` con un 301).

HSTS va sin `includeSubDomains` ni `preload`: un subdominio sin HTTPS quedaria
inalcanzable, y salir de la lista de precarga tarda meses.

La CSP estricta va solo en las respuestas JSON: `/docs` y la pasarela simulada
de desarrollo (`/dev`) son HTML que carga sus propios recursos.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HSTS = "max-age=31536000"

_ALWAYS = {
    "Strict-Transport-Security": HSTS,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
_JSON_CSP = "default-src 'none'; frame-ancestors 'none'"


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _ALWAYS.items():
                    headers.setdefault(name, value)
                if headers.get("content-type", "").startswith("application/json"):
                    headers.setdefault("Content-Security-Policy", _JSON_CSP)
            await send(message)

        await self.app(scope, receive, send_with_headers)
