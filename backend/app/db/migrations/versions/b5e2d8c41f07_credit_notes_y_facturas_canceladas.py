"""credit_notes y facturas canceladas

Fase 5, paso 5.4 (docs/PLATAFORMA_COMPLETA.md §3.17, "Paso 5.4", punto 12).
Solo DDL.

- `credit_notes`: la nota credito electronica de un reembolso o de una
  anulacion de la pasarela, con lo que se congela antes del primer envio y su
  emision, como la factura. Un reembolso tiene a lo sumo una.
- `invoices`: el estado `cancelled` (la factura no se emite: su pago se
  reembolso entero o se anulo antes de que la DIAN la aceptara; la contadora,
  2026-11-11), con `cancelled_at` y `cancel_reason`.

El downgrade borra la tabla y las columnas, y pasa las facturas `cancelled` a
`failed` para que quepan en el CHECK anterior: `failed` tampoco se emite sola,
asi que ninguna sale por el downgrade. Se pierde por que no se emitieron.

Revision ID: b5e2d8c41f07
Revises: 7b636895d186
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b5e2d8c41f07"
down_revision: str | None = "7b636895d186"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = "('pending', 'sending', 'issued', 'accepted', 'rejected', 'failed', 'cancelled')"
OLD_STATUSES = "('pending', 'sending', 'issued', 'accepted', 'rejected', 'failed')"


def upgrade() -> None:
    op.drop_constraint("invoice_status", "invoices", type_="check")
    op.create_check_constraint("invoice_status", "invoices", f"status IN {STATUSES}")
    op.add_column("invoices", sa.Column("cancelled_at", sa.DateTime(timezone=True)))
    op.add_column("invoices", sa.Column("cancel_reason", sa.String(length=20)))
    op.create_check_constraint(
        "invoice_cancel_reason",
        "invoices",
        "cancel_reason IN ('refunded', 'voided', 'annulled_in_siigo')",
    )

    op.create_table(
        "credit_notes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("invoice_id", sa.UUID(), nullable=False),
        sa.Column("refund_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("prepared_at", sa.DateTime(timezone=True)),
        sa.Column("idempotency_key", sa.String(length=30)),
        sa.Column("cop_cents", sa.BigInteger()),
        sa.Column("observations", sa.Text()),
        sa.Column("description", sa.String(length=500)),
        sa.Column("waiting_reason", sa.String(length=40)),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("issue_date", sa.Date()),
        sa.Column("provider_id", sa.String(length=64)),
        sa.Column("provider_name", sa.String(length=40)),
        sa.Column("provider_total", sa.Numeric(precision=18, scale=2)),
        sa.Column("stamp_status", sa.String(length=20)),
        sa.Column("cude", sa.String(length=200)),
        sa.Column("mail_status", sa.String(length=20)),
        sa.Column("last_error_codes", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("last_error_message", sa.String(length=500)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount_cents > 0", name="ck_credit_notes_amount_positive"),
        sa.CheckConstraint(
            "cop_cents IS NULL OR cop_cents > 0", name="ck_credit_notes_cop_positive"
        ),
        sa.CheckConstraint("reason IN (1, 2)", name="ck_credit_notes_reason"),
        sa.CheckConstraint(f"status IN {STATUSES}", name="credit_note_status"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["refund_id"], ["payment_refunds.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("refund_id", name="uq_credit_notes_refund_id"),
    )
    op.create_index(op.f("ix_credit_notes_invoice_id"), "credit_notes", ["invoice_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_credit_notes_invoice_id"), table_name="credit_notes")
    op.drop_table("credit_notes")
    op.drop_constraint("invoice_cancel_reason", "invoices", type_="check")
    op.drop_column("invoices", "cancel_reason")
    op.drop_column("invoices", "cancelled_at")
    op.drop_constraint("invoice_status", "invoices", type_="check")
    op.execute("UPDATE invoices SET status = 'failed' WHERE status = 'cancelled'")
    op.create_check_constraint("invoice_status", "invoices", f"status IN {OLD_STATUSES}")
