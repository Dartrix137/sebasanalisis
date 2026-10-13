"""subscriptions se amplia, tabla payments y payment_events sin suscripcion obligatoria

Fase 4, paso 5, entrega 1 (docs/PLATAFORMA_COMPLETA.md §3.2). Solo DDL, y solo
lo que no depende de los datos: las columnas nuevas entran nullable. La
migracion siguiente pasa los datos y la tercera cierra (NOT NULL, CHECK, indice
unico parcial y retiro de las columnas viejas).

- `subscriptions.plan_id` era texto suelto: se renombra a `plan_code_legacy` y
  entra un `plan_id` nuevo, llave foranea a `plans`.
- `payments`: un intento de cobro de un periodo. `user_id` y `subscription_id`
  son SET NULL: al eliminar una cuenta el pago se conserva sin usuario
  (decidido el 2026-10-13).
- `payment_events`: `subscription_id` deja de ser obligatoria y pasa de CASCADE
  a SET NULL; entran `payment_id`, `event_type`, `processed_at` y `created_at`.

El downgrade borra los eventos sin suscripcion: en el schema anterior no caben.

Revision ID: e7b1c5a2d904
Revises: d2f6a18c4b93
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7b1c5a2d904"
down_revision: str | None = "d2f6a18c4b93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    # ---- subscriptions ----
    op.alter_column("subscriptions", "plan_id", new_column_name="plan_code_legacy")
    op.add_column("subscriptions", sa.Column("plan_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_subscriptions_plan_id_plans",
        "subscriptions",
        "plans",
        ["plan_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f("ix_subscriptions_plan_id"), "subscriptions", ["plan_id"])
    op.add_column(
        "subscriptions",
        sa.Column(
            "renewal_mode",
            sa.Enum(
                "manual",
                "automatic",
                name="subscription_renewal_mode",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default="manual",
            nullable=False,
        ),
    )
    op.add_column("subscriptions", sa.Column("price_cents", sa.Integer(), nullable=True))
    op.add_column("subscriptions", sa.Column("currency", sa.String(length=3), nullable=True))
    op.add_column("subscriptions", sa.Column("coupon_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_subscriptions_coupon_id_coupons",
        "subscriptions",
        "coupons",
        ["coupon_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "subscriptions", sa.Column("discount_periods_remaining", sa.Integer(), nullable=True)
    )
    op.add_column("subscriptions", sa.Column("current_period_start", _TS, nullable=True))
    op.add_column(
        "subscriptions",
        sa.Column(
            "cancel_at_period_end", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.add_column(
        "subscriptions", sa.Column("payment_source_id", sa.String(length=255), nullable=True)
    )
    op.add_column("subscriptions", sa.Column("card_brand", sa.String(length=50), nullable=True))
    op.add_column("subscriptions", sa.Column("card_last4", sa.String(length=4), nullable=True))
    op.add_column("subscriptions", sa.Column("next_charge_at", _TS, nullable=True))
    op.add_column(
        "subscriptions",
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "subscriptions",
        sa.Column("created_at", _TS, server_default=sa.text("now()"), nullable=False),
    )
    op.add_column(
        "subscriptions",
        sa.Column("updated_at", _TS, server_default=sa.text("now()"), nullable=False),
    )
    op.add_column("subscriptions", sa.Column("canceled_at", _TS, nullable=True))

    # ---- payments ----
    op.create_table(
        "payments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("coupon_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("reference", sa.String(length=255), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "initial",
                "renewal",
                name="payment_kind",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("period_start", _TS, nullable=True),
        sa.Column("period_end", _TS, nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("discount_cents", sa.Integer(), server_default="0", nullable=False),
        sa.Column("provider_transaction_id", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "declined",
                "voided",
                "error",
                name="payment_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", _TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", _TS, nullable=True),
        sa.CheckConstraint("amount_cents > 0", name="ck_payments_amount_positive"),
        sa.CheckConstraint("discount_cents >= 0", name="ck_payments_discount_not_negative"),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["coupon_id"], ["coupons.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference"),
    )
    op.create_index(op.f("ix_payments_subscription_id"), "payments", ["subscription_id"])
    op.create_index(op.f("ix_payments_user_id"), "payments", ["user_id"])
    op.create_index(
        op.f("ix_payments_provider_transaction_id"), "payments", ["provider_transaction_id"]
    )

    # ---- payment_events ----
    op.alter_column("payment_events", "subscription_id", existing_type=sa.UUID(), nullable=True)
    op.drop_constraint(
        "payment_events_subscription_id_fkey", "payment_events", type_="foreignkey"
    )
    op.create_foreign_key(
        "payment_events_subscription_id_fkey",
        "payment_events",
        "subscriptions",
        ["subscription_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("payment_events", sa.Column("payment_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_payment_events_payment_id_payments",
        "payment_events",
        "payments",
        ["payment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_payment_events_payment_id"), "payment_events", ["payment_id"])
    op.add_column(
        "payment_events", sa.Column("event_type", sa.String(length=100), nullable=True)
    )
    op.add_column("payment_events", sa.Column("processed_at", _TS, nullable=True))
    op.add_column(
        "payment_events",
        sa.Column("created_at", _TS, server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    # ---- payment_events ----
    op.drop_column("payment_events", "created_at")
    op.drop_column("payment_events", "processed_at")
    op.drop_column("payment_events", "event_type")
    op.drop_index(op.f("ix_payment_events_payment_id"), table_name="payment_events")
    op.drop_constraint(
        "fk_payment_events_payment_id_payments", "payment_events", type_="foreignkey"
    )
    op.drop_column("payment_events", "payment_id")
    # En el schema anterior todo evento tiene suscripcion.
    op.execute("DELETE FROM payment_events WHERE subscription_id IS NULL")
    op.drop_constraint(
        "payment_events_subscription_id_fkey", "payment_events", type_="foreignkey"
    )
    op.create_foreign_key(
        "payment_events_subscription_id_fkey",
        "payment_events",
        "subscriptions",
        ["subscription_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("payment_events", "subscription_id", existing_type=sa.UUID(), nullable=False)

    # ---- payments ----
    op.drop_index(op.f("ix_payments_provider_transaction_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_user_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_subscription_id"), table_name="payments")
    op.drop_table("payments")

    # ---- subscriptions ----
    for column in (
        "canceled_at",
        "updated_at",
        "created_at",
        "retry_count",
        "next_charge_at",
        "card_last4",
        "card_brand",
        "payment_source_id",
        "cancel_at_period_end",
        "current_period_start",
        "discount_periods_remaining",
    ):
        op.drop_column("subscriptions", column)
    op.drop_constraint(
        "fk_subscriptions_coupon_id_coupons", "subscriptions", type_="foreignkey"
    )
    op.drop_column("subscriptions", "coupon_id")
    op.drop_column("subscriptions", "currency")
    op.drop_column("subscriptions", "price_cents")
    op.drop_column("subscriptions", "renewal_mode")
    op.drop_index(op.f("ix_subscriptions_plan_id"), table_name="subscriptions")
    op.drop_constraint("fk_subscriptions_plan_id_plans", "subscriptions", type_="foreignkey")
    op.drop_column("subscriptions", "plan_id")
    op.alter_column("subscriptions", "plan_code_legacy", new_column_name="plan_id")
