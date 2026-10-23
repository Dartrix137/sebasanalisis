"""invoices: factura pendiente por pago aprobado

Fase 5, paso 5.2 (docs/PLATAFORMA_COMPLETA.md §3.17). Solo DDL.

- `invoices`: una fila por pago aprobado (unica por `payment_id`), que nace
  `pending` en la misma transaccion que aprueba el pago. La emision con Dataico
  es del paso 5.4; las tasas de cambio y el monto en pesos entran entonces, con
  su propia migracion.

Sin backfill: los pagos aprobados que habia al desplegar eran del sandbox de
Wompi, sin dinero real, y no se facturan.

El downgrade borra la tabla: se pierden las facturas pendientes.

Revision ID: 5dc9670480c1
Revises: 7d82b3f54867
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5dc9670480c1"
down_revision: str | None = "7d82b3f54867"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invoices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("payment_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("operation_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id"),
    )


def downgrade() -> None:
    op.drop_table("invoices")
