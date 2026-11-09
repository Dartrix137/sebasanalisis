"""billing_profiles: datos de facturacion de cada cuenta

Fase 5, paso 5.4 (docs/PLATAFORMA_COMPLETA.md §3.17, "Paso 5.4", punto 8). Solo
DDL.

- `billing_profiles`: nombres, apellidos, tipo y numero de documento, pais,
  departamento, ciudad (codigos de Siigo) y direccion. Una fila por cuenta, que
  se borra con ella.

Sin backfill: los datos los da cada cliente al pagar.

El downgrade borra la tabla: se pierden los datos de facturacion guardados.

Revision ID: 750301b44179
Revises: c4faf46696b1
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "750301b44179"
down_revision: str | None = "c4faf46696b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "billing_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("first_names", sa.String(length=50), nullable=False),
        sa.Column("last_names", sa.String(length=50), nullable=False),
        sa.Column(
            "id_type",
            sa.Enum(
                "13",
                "22",
                "50",
                "41",
                "42",
                name="billing_id_type",
                native_enum=False,
                create_constraint=True,
                length=2,
            ),
            nullable=False,
        ),
        sa.Column("id_number", sa.String(length=20), nullable=False),
        sa.Column("country_code", sa.String(length=4), nullable=False),
        sa.Column("state_code", sa.String(length=10), nullable=False),
        sa.Column("city_code", sa.String(length=10), nullable=False),
        sa.Column("address", sa.String(length=256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("billing_profiles")
