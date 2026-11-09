"""exchange_rates: tasas de cambio con su vigencia y su fuente

Fase 5, paso 5.4 (docs/PLATAFORMA_COMPLETA.md §3.17, "Paso 5.4", punto 5). Solo
DDL.

- `exchange_rates`: la TRM de datos.gov.co (`USD/COP`, a veces de varios dias)
  y la tasa de referencia del BCE (`EUR/USD`, de un dia), guardadas al
  consultarlas. Una fila por par y dia de inicio.

Sin backfill: las tasas se consultan cuando una factura las necesita.

El downgrade borra la tabla: se pierden las tasas guardadas (las facturas que
ya las congelaron no dependen de ella).

Revision ID: c4faf46696b1
Revises: 22780db115af
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4faf46696b1"
down_revision: str | None = "22780db115af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exchange_rates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "pair",
            sa.Enum(
                "USD/COP",
                "EUR/USD",
                name="exchange_rate_pair",
                native_enum=False,
                create_constraint=True,
                length=10,
            ),
            nullable=False,
        ),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(precision=20, scale=10), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rate > 0", name="ck_exchange_rates_rate_positive"),
        sa.CheckConstraint("valid_to >= valid_from", name="ck_exchange_rates_validity"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pair", "valid_from", name="uq_exchange_rates_pair_valid_from"),
    )


def downgrade() -> None:
    op.drop_table("exchange_rates")
