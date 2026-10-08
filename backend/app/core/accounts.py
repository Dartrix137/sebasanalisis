"""Reglas sobre las cuentas que usan mas de un endpoint."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User


def is_last_active_admin(db: Session, user: User) -> bool:
    """Si `user` es administrador y no hay OTRO administrador activo.

    Sin administrador nadie puede gestionar juegos, usuarios ni documentos
    legales. Uno suspendido no cuenta: no puede administrar
    (`api/deps.require_admin`), asi que no es un relevo.
    """
    if user.role != "admin":
        return False
    others = db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.role == "admin", User.is_active.is_(True), User.id != user.id)
    )
    return not others
