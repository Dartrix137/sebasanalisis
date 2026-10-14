"""pagos: anulacion posterior a la aprobacion y reembolsos registrados

Fase 4, paso 6, entrega 1 (docs/PLATAFORMA_COMPLETA.md §4.3 y §4.8). Solo DDL.

- `payments.reversed_at` y `payments.reversal_note`: un pago aprobado que el
  proveedor anulo despues, y que se hizo con el periodo que habia comprado.
- `payment_refunds`: los reembolsos hechos en el panel del proveedor que un
  administrador registra a mano. No mueven el pago ni el acceso.

El downgrade borra la tabla y las dos columnas: los reembolsos registrados y la
nota de las anulaciones se pierden.

Revision ID: d9a4c2e7b815
Revises: c8e3a5d7f216
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9a4c2e7b815"
down_revision: str | None = "c8e3a5d7f216"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payments", sa.Column("reversal_note", sa.Text(), nullable=True))

    op.create_table(
        "payment_refunds",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("payment_id", sa.UUID(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_refund_id", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("admin_user_id", sa.UUID(), nullable=True),
        sa.Column("admin_email", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount_cents > 0", name="ck_payment_refunds_amount_positive"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["admin_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_payment_refunds_payment_id"), "payment_refunds", ["payment_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_payment_refunds_payment_id"), table_name="payment_refunds")
    op.drop_table("payment_refunds")
    op.drop_column("payments", "reversal_note")
    op.drop_column("payments", "reversed_at")
