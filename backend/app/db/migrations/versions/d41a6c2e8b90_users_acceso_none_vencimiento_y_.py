"""users: access_type acepta 'none', vencimiento del acceso e is_active

Fase 4, paso 3 (docs/PLATAFORMA_COMPLETA.md §2.3). Solo DDL.

- `access_type` acepta `none`: cuenta sin acceso hasta pagar o hasta que un
  administrador se lo otorgue. `trial` sigue aceptado aqui; la migracion
  siguiente mueve las filas y la de despues lo retira del CHECK.
- `access_expires_at`: vencimiento del acceso `invited`. Null = sin vencimiento.
- `is_active`: permite suspender una cuenta sin borrarla.

Limitacion del downgrade: el esquema anterior no conoce `none`, asi que esas
cuentas bajan como `trial`, que alli era el valor de una cuenta recien creada.

Revision ID: d41a6c2e8b90
Revises: c3f81a5d7e20
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d41a6c2e8b90"
down_revision: str | None = "c3f81a5d7e20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "access_type"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "users", type_="check")
    op.create_check_constraint(
        CONSTRAINT, "users", "access_type IN ('none', 'trial', 'invited', 'full')"
    )
    op.add_column(
        "users", sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "is_active")
    op.drop_column("users", "access_expires_at")
    op.execute("UPDATE users SET access_type = 'trial' WHERE access_type = 'none'")
    op.drop_constraint(CONSTRAINT, "users", type_="check")
    op.create_check_constraint(
        CONSTRAINT, "users", "access_type IN ('trial', 'invited', 'full')"
    )
