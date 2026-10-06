"""Hash de contrasenas (argon2) y emision/verificacion de JWT.

Decisiones de `docs/ARQUITECTURA_Y_ESTADISTICA.md` §3.6:
- Hash con algoritmo de derivacion de clave, nunca texto plano.
- Access token de vida corta + refresh token de vida larga.
- Mensajes de error genericos que no revelan si un correo existe.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Compara en tiempo constante. Devuelve False en vez de propagar la excepcion."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True si el hash quedo con parametros mas debiles que los actuales."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


def create_token(user_id: UUID, token_type: TokenType, *, token_version: int) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    if token_type == "access":
        expires = now + timedelta(minutes=settings.access_token_expire_minutes)
    else:
        expires = now + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        # Version de sesion del usuario al emitir (users.token_version).
        "ver": token_version,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


class TokenError(Exception):
    """Token ausente, malformado, expirado, o de un tipo distinto al esperado."""


@dataclass(frozen=True)
class TokenClaims:
    user_id: UUID
    # Quien llama la compara con `users.token_version`: si no coinciden, la
    # sesion fue revocada (la contrasena cambio despues de emitir el token).
    token_version: int


def decode_token(token: str, expected_type: TokenType) -> TokenClaims:
    """Devuelve el usuario y la version de sesion del token, o lanza TokenError.

    Verifica explicitamente el claim `type`: un refresh token no debe servir para
    autenticar una peticion normal, ni un access token para renovar sesion.

    Un token sin `ver` es anterior a la revocacion de sesiones y se lee como
    version 0, que es con la que arrancan todas las cuentas: desplegar esto no
    cierra la sesion de nadie.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError("Token invalido o expirado") from exc

    if payload.get("type") != expected_type:
        raise TokenError("Token invalido o expirado")
    try:
        return TokenClaims(user_id=UUID(payload["sub"]), token_version=int(payload.get("ver", 0)))
    except (KeyError, ValueError, TypeError) as exc:
        raise TokenError("Token invalido o expirado") from exc
