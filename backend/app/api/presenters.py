"""Respuestas que no salen solo de las columnas de un modelo."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.access import has_access
from app.core.accounts import is_last_active_admin
from app.models import User
from app.schemas.auth import AccessInfo, UserAccount, UserResponse


def user_response(db: Session, user: User, now: datetime | None = None) -> UserResponse:
    """La cuenta con su decision de acceso.

    La decision es la de `core/access.has_access`, la misma que aplica
    `RequireAccess`: aqui solo se muestra, no se vuelve a decidir.
    """
    decision = has_access(db, user, now or datetime.now(UTC))
    return UserResponse(
        **UserAccount.model_validate(user).model_dump(),
        access=AccessInfo.model_validate(decision),
        can_delete_account=not is_last_active_admin(db, user),
    )
