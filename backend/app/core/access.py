"""Control de acceso a los juegos (docs/PLATAFORMA_COMPLETA.md §2).

`has_access` es la UNICA funcion que decide si una cuenta puede usar la mesa.
Ningun endpoint repite esta logica: los routers de juego la aplican con la
dependencia `RequireAccess` (`api/deps.py`).

Estado en el paso 2 de la Fase 4: solo esta escrita la regla de consentimiento
legal (§2.2 n.º 2). Las demas fuentes de §2.2 (cuenta suspendida, rol, acceso
manual, suscripcion, juego incluido en el plan) llegan en el paso 3 y se
agregan AQUI, en el orden de ese apartado. Hasta entonces, una cuenta al dia
con sus consentimientos usa la mesa, como antes de este paso.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.core import legal
from app.models import User

# `open`: todavia no hay control de acceso por pago (paso 3).
AccessReason = Literal["open", "consent_required"]


@dataclass(frozen=True)
class AccessDecision:
    granted: bool
    reason: AccessReason


def has_access(db: Session, user: User, now: datetime) -> AccessDecision:
    # `now` no se usa todavia: los vencimientos (acceso invitado, periodo de la
    # suscripcion) son del paso 3. Esta en la firma para que no cambie entonces.
    del now

    # §2.2 n.º 2: sin los documentos vigentes aceptados y la mayoria de edad
    # declarada no hay mesa, sea quien sea. Va antes que el rol: un
    # administrador tambien acepta.
    if legal.pending_consent(db, user).any:
        return AccessDecision(granted=False, reason="consent_required")

    return AccessDecision(granted=True, reason="open")
