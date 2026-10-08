"""users: access_type deja de aceptar 'trial'

Fase 4, paso 3 (docs/PLATAFORMA_COMPLETA.md §2.3). Solo DDL. La migracion
anterior ya movio las filas, asi que ninguna queda en `trial` y el CHECK nuevo
se crea sin tocar datos. Ya no hay prueba gratuita.

Revision ID: f63c8e40adb2
Revises: e52b7d3f9ca1
Create Date: 2026-10-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f63c8e40adb2"
down_revision: str | None = "e52b7d3f9ca1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "access_type"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "users", type_="check")
    op.create_check_constraint(
        CONSTRAINT, "users", "access_type IN ('none', 'invited', 'full')"
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "users", type_="check")
    op.create_check_constraint(
        CONSTRAINT, "users", "access_type IN ('none', 'trial', 'invited', 'full')"
    )
