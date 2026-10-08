"""Control de acceso a los juegos (docs/PLATAFORMA_COMPLETA.md §2).

`has_access` es la UNICA funcion que decide si una cuenta puede usar la mesa.
Ningun endpoint repite esta logica: los routers de juego la aplican con la
dependencia `RequireAccess` (`api/deps.py`), y `GET /auth/me` y el panel de
administracion muestran la misma decision.

Las reglas van en el orden de §2.2. Falta una, que llega con su paso: exigir
que el plan de la suscripcion incluya el juego (§7.4, paso 7).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import legal
from app.models import Subscription, User

AccessReason = Literal[
    # Con acceso: de donde sale.
    "admin",
    "full",
    "invited",
    "subscription",
    # Sin acceso: por que.
    "suspended",
    "consent_required",
    "expired",
    "no_access",
]

# `canceled` cuenta: la cancelacion es al final del periodo ya pagado (§3.6).
_SUBSCRIPTION_STATUSES_WITH_ACCESS = ("active", "canceled")


@dataclass(frozen=True)
class AccessDecision:
    granted: bool
    reason: AccessReason
    # Hasta cuando vale el acceso, si vence; o cuando vencio, si el motivo es
    # `expired`. Null en los accesos sin vencimiento.
    until: datetime | None = None


def has_access(db: Session, user: User, now: datetime) -> AccessDecision:
    # 1. Cuenta suspendida por un administrador: sin acceso, pase lo que pase.
    if not user.is_active:
        return AccessDecision(granted=False, reason="suspended")

    # 2. Sin los documentos vigentes aceptados y la mayoria de edad declarada
    #    no hay mesa. Va antes que el rol: un administrador tambien acepta.
    if legal.pending_consent(db, user).any:
        return AccessDecision(granted=False, reason="consent_required")

    # 3. Administrador.
    if user.role == "admin":
        return AccessDecision(granted=True, reason="admin")

    # 4. Acceso completo sin vencimiento: cortesias permanentes, equipo interno.
    if user.access_type == "full":
        return AccessDecision(granted=True, reason="full")

    # 5. Acceso manual con vencimiento opcional.
    invited_expired_at: datetime | None = None
    if user.access_type == "invited":
        if user.access_expires_at is None or user.access_expires_at > now:
            return AccessDecision(granted=True, reason="invited", until=user.access_expires_at)
        invited_expired_at = user.access_expires_at

    # 6. Suscripcion con el periodo pagado todavia vigente.
    period_end = db.scalar(
        select(Subscription.current_period_end)
        .where(
            Subscription.user_id == user.id,
            Subscription.status.in_(_SUBSCRIPTION_STATUSES_WITH_ACCESS),
            Subscription.current_period_end.is_not(None),
        )
        .order_by(Subscription.current_period_end.desc())
        .limit(1)
    )
    if period_end is not None and period_end > now:
        return AccessDecision(granted=True, reason="subscription", until=period_end)

    # 8. Cualquier otro caso. Se distingue "tuvo acceso y vencio" de "nunca
    #    tuvo" para que la pantalla diga lo que paso.
    vencimientos = [d for d in (invited_expired_at, period_end) if d is not None]
    if vencimientos:
        return AccessDecision(granted=False, reason="expired", until=max(vencimientos))
    return AccessDecision(granted=False, reason="no_access")
