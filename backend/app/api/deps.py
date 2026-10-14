"""Dependencias compartidas de la API."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access import AccessDecision, has_access
from app.core.security import TokenError, decode_token
from app.db.session import get_db
from app.models import Game, GameSession, GameVariant, User

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
    "game_not_in_plan": "Este juego no está incluido en tu plan.",
}


def _deny_unless_granted(decision: AccessDecision) -> None:
    if not decision.granted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": decision.reason, "message": ACCESS_DENIED_MESSAGES[decision.reason]},
        )


def require_access(user: CurrentUser, db: DbSession) -> User:
    """Exige acceso a los juegos. La decision es de `core/access.has_access`.

    Responde 403 con el motivo en `detail.code`, para que el cliente muestre la
    pantalla que corresponde sin adivinar.
    """
    _deny_unless_granted(has_access(db, user, datetime.now(UTC)))
    return user


def require_game_access(db: Session, user: User, game: Game) -> None:
    """Exige acceso a un juego en particular (regla n.º 7 de §2.2).

    `RequireAccess` corre antes de saber de que juego se trata; donde el juego
    se conoce (al abrir una mesa y en cada llamada sobre una mesa) se vuelve a
    preguntar a `has_access` con el juego. Responde `403 game_not_in_plan` si
    el plan de la suscripcion no lo incluye.
    """
    _deny_unless_granted(has_access(db, user, datetime.now(UTC), game))


def require_session_game_access(request: Request, user: CurrentUser, db: DbSession) -> None:
    """Exige acceso al juego de la mesa de la URL (`{session_id}`).

    Va en los routers de la mesa junto a `RequireAccess`, y por eso corre antes
    que el endpoint y antes de validar el cuerpo: una llamada sobre una mesa de
    un juego que el plan ya no incluye responde `403 game_not_in_plan`, sea cual
    sea el endpoint. Asi un endpoint nuevo sobre una mesa no puede olvidarlo.

    Una ruta sin `{session_id}` (abrir o listar mesas) no hace nada aqui. Si la
    mesa no existe o es de otro, tampoco: el endpoint responde 404.

    El estado del juego no se mira: una mesa abierta sigue funcionando aunque
    su juego pase a oculto o a "proximamente", igual que con una variante
    desactivada.
    """
    raw = request.path_params.get("session_id")
    if raw is None:
        return
    try:
        session_id = uuid.UUID(str(raw))
    except ValueError:
        return
    game = db.scalar(
        select(Game)
        .join(GameVariant, GameVariant.game_id == Game.id)
        .join(GameSession, GameSession.game_variant_id == GameVariant.id)
        .where(GameSession.id == session_id, GameSession.user_id == user.id)
    )
    if game is not None:
        require_game_access(db, user, game)


RequireAccess = Depends(require_access)
RequireGameAccess = Depends(require_session_game_access)
