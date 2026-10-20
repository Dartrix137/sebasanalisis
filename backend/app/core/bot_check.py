"""Verificacion contra bots en el registro, el ingreso y el olvido de contrasena.

Proveedor: Cloudflare Turnstile (decidido el 2026-10-20, paso 9). El widget del
navegador entrega un token de un solo uso, y aqui se valida contra la API de
Cloudflare antes de seguir. Validarlo en el servidor es obligatorio: el widget
solo no protege nada.

Algoritmo y nombres, de la documentacion oficial vigente de Cloudflare
(consultada el 2026-10-20):

- Validacion: https://developers.cloudflare.com/turnstile/get-started/server-side-validation/
  `POST https://challenges.cloudflare.com/turnstile/v0/siteverify` con `secret`,
  `response` y, opcional, `remoteip`. Responde JSON con `success`, `action`,
  `hostname` y `error-codes`. El token dura 300 segundos, se valida una sola
  vez y mide como maximo 2048 caracteres.
- Llaves de prueba: https://developers.cloudflare.com/turnstile/troubleshooting/testing/

Sin las dos llaves configuradas la verificacion queda apagada (desarrollo,
tests de punta a punta), como el pago sin llaves de Wompi. Con una sola, la API
no arranca: seria un formulario que nunca deja pasar o uno que no protege.

Si Cloudflare no responde, no se deja pasar (falla cerrado): sin Cloudflare el
widget tampoco carga, asi que nadie tendria un token valido de todos modos.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
HTTP_TIMEOUT_SECONDS = 5.0
MAX_TOKEN_LENGTH = 2048


class BotChecker(Protocol):
    @property
    def site_key(self) -> str | None:
        """La llave publica del widget, o None si la verificacion esta apagada."""
        ...

    def verify(self, token: str | None, *, remote_ip: str | None, action: str) -> bool:
        """True si el token prueba que hubo una persona en el formulario `action`."""
        ...


class DisabledBotChecker:
    """Sin llaves: no se le pide nada al navegador y todo pasa."""

    site_key: str | None = None

    def verify(self, token: str | None, *, remote_ip: str | None, action: str) -> bool:
        return True


@dataclass
class TurnstileChecker:
    site_key: str | None
    secret_key: str
    # Los tests pasan un transporte que responde sin salir a la red.
    transport: httpx.BaseTransport | None = None

    def verify(self, token: str | None, *, remote_ip: str | None, action: str) -> bool:
        if not token or len(token) > MAX_TOKEN_LENGTH:
            return False
        data = {"secret": self.secret_key, "response": token}
        if remote_ip:
            data["remoteip"] = remote_ip
        try:
            with httpx.Client(transport=self.transport, timeout=HTTP_TIMEOUT_SECONDS) as client:
                response = client.post(SITEVERIFY_URL, data=data)
            body = response.json()
        except (httpx.HTTPError, ValueError):
            # Ni el secreto ni el token van al log.
            logger.warning("Verificacion contra bots: Cloudflare no respondio")
            return False
        if not isinstance(body, dict) or body.get("success") is not True:
            return False
        # La accion que declaro el widget tiene que ser la de este formulario:
        # un token sacado del ingreso no sirve para el registro. Las llaves de
        # prueba no devuelven accion, y entonces no hay nada que comparar.
        declared = body.get("action")
        return not declared or declared == action


def build_bot_checker(settings: Settings) -> BotChecker:
    site_key = settings.turnstile_site_key.strip()
    secret_key = settings.turnstile_secret_key.strip()
    if not site_key and not secret_key:
        return DisabledBotChecker()
    if not site_key or not secret_key:
        raise ValueError(
            "TURNSTILE_SITE_KEY y TURNSTILE_SECRET_KEY van juntas: falta una de las dos."
        )
    return TurnstileChecker(site_key=site_key, secret_key=secret_key)


@lru_cache
def get_bot_checker() -> BotChecker:
    """Dependencia de FastAPI. Los tests la sustituyen."""
    return build_bot_checker(get_settings())
