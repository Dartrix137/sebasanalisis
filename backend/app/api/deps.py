"""Dependencias compartidas de la API."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.access import has_access
from app.core.security import TokenError, decode_token
from app.db.session import get_db
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Credenciales invalidas o sesion expirada",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    if credentials is None:
        raise _CREDENTIALS_ERROR
    try:
        claims = decode_token(credentials.credentials, "access")
    except TokenError:
        raise _CREDENTIALS_ERROR from None
    user = db.get(User, claims.user_id)
    # Una version distinta significa que la contrasena cambio despues de emitir
    # el token: esa sesion quedo revocada (§5.3 de la Fase 4).
    if user is None or claims.token_version != user.token_version:
        raise _CREDENTIALS_ERROR
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    # Un administrador suspendido deja de serlo hasta que otro lo reactive.
    if user.role != "admin" or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Requiere permisos de administrador"
        )
    return user


AdminUser = Annotated[User, Depends(require_admin)]


# Lo que se le dice a la cuenta por cada motivo de rechazo. El cliente decide
# la pantalla por `detail.code`; el texto es el respaldo si no la reconoce.
ACCESS_DENIED_MESSAGES = {
    "suspended": "Tu cuenta está suspendida.",
    "consent_required": (
        "Antes de continuar debes aceptar la versión vigente de los documentos legales. "
        "Recarga la página."
    ),
    "expired": "Tu acceso venció.",
    "no_access": "Tu cuenta no tiene acceso activo.",
}


def require_access(user: CurrentUser, db: DbSession) -> User:
    """Exige acceso a los juegos. La decision es de `core/access.has_access`.

    Responde 403 con el motivo en `detail.code`, para que el cliente muestre la
    pantalla que corresponde sin adivinar.
    """
    decision = has_access(db, user, datetime.now(UTC))
    if not decision.granted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": decision.reason, "message": ACCESS_DENIED_MESSAGES[decision.reason]},
        )
    return user


RequireAccess = Depends(require_access)
