"""Guardar y leer los datos de facturacion de una cuenta
(docs/PLATAFORMA_COMPLETA.md §3.17, "Paso 5.4", punto 8).

Las reglas son de `billing/billing_profile.py` (puro). Aqui solo se guardan.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.billing_profile import BillingProfileData
from app.models import BillingProfile


def get(db: Session, user_id: UUID) -> BillingProfile | None:
    return db.scalar(select(BillingProfile).where(BillingProfile.user_id == user_id))


def has_profile(db: Session, user_id: UUID) -> bool:
    return db.scalar(select(BillingProfile.id).where(BillingProfile.user_id == user_id)) is not None


def save(db: Session, user_id: UUID, data: BillingProfileData) -> BillingProfile:
    """Crea o reemplaza los datos de la cuenta. NO hace commit."""
    profile = get(db, user_id)
    if profile is None:
        profile = BillingProfile(user_id=user_id)
        db.add(profile)
    profile.first_names = data.first_names
    profile.last_names = data.last_names
    profile.id_type = data.id_type
    profile.id_number = data.id_number
    profile.country_code = data.country_code
    profile.state_code = data.state_code
    profile.city_code = data.city_code
    profile.address = data.address
    db.flush()
    return profile
