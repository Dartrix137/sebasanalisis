"""Emision y consumo de los tokens de un solo uso (§5.1 de la Fase 4).

El token es aleatorio, viaja en claro solo dentro del enlace del correo, y en la
base queda unicamente su SHA-256. Se consume una vez: `used_at` lo marca.

Ninguna funcion hace commit: el token se emite o se consume en la misma
transaccion que el cambio que lo acompana (crear la cuenta, cambiar la
contrasena), y es el endpoint quien la cierra.
"""

import hashlib
import secrets
from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import User, UserToken

TOKEN_TTL: dict[str, timedelta] = {
    "verify_email": timedelta(hours=48),
    "reset_password": timedelta(hours=1),
    "change_email": timedelta(hours=24),
}


class InvalidTokenError(Exception):
    """El token no existe, ya se uso, vencio o es de otro proposito.

    Es una sola excepcion a proposito: quien presenta un token malo no recibe
    pistas de cual de las cuatro cosas fallo.
    """


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue_token(
    db: Session,
    user: User,
    purpose: str,
    *,
    now: datetime,
    new_email: str | None = None,
) -> str:
    """Crea un token y devuelve su valor en claro, que no se vuelve a ver.

    Emitir uno nuevo invalida los anteriores sin usar del mismo proposito y
    usuario: pedir el correo dos veces deja valido solo el ultimo enlace.
    """
    db.execute(
        update(UserToken)
        .where(
            UserToken.user_id == user.id,
            UserToken.purpose == purpose,
            UserToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    raw_token = secrets.token_urlsafe(32)
    db.add(
        UserToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=hash_token(raw_token),
            new_email=new_email,
            expires_at=now + TOKEN_TTL[purpose],
        )
    )
    return raw_token


def consume_token(
    db: Session, raw_token: str, purposes: Iterable[str], *, now: datetime
) -> UserToken:
    """Marca el token como usado y lo devuelve, o lanza `InvalidTokenError`.

    La fila se bloquea (`FOR UPDATE`) para que dos peticiones simultaneas con el
    mismo enlace no lo consuman las dos.
    """
    token = db.scalar(
        select(UserToken).where(UserToken.token_hash == hash_token(raw_token)).with_for_update()
    )
    if (
        token is None
        or token.purpose not in set(purposes)
        or token.used_at is not None
        or token.expires_at <= now
    ):
        raise InvalidTokenError
    token.used_at = now
    return token
