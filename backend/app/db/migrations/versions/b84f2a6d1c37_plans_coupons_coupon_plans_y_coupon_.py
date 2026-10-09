"""plans, coupons, coupon_plans y coupon_redemptions

Fase 4, paso 4 (docs/PLATAFORMA_COMPLETA.md §3.2 y §3.10). Solo DDL: el plan
unico lo inserta la migracion siguiente.

- `plans`: lo que se cobra (`price_cents`, `currency`) y, aparte, un precio de
  presentacion (`display_price_cents`, `display_currency`) que es solo visual.
- `coupons`: el porcentaje va de 1 a 99; un cupon nunca deja el total en cero.
- `coupon_plans`: sin filas, el cupon aplica a todos los planes.
- `coupon_redemptions`: un uso por cuenta. Las escribe el pago (paso 5).

`subscriptions.plan_id` sigue siendo texto suelto: pasa a llave foranea en el
paso 5, con el resto de la ampliacion de esa tabla.

Revision ID: b84f2a6d1c37
Revises: a74d9f51bec3
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b84f2a6d1c37"
down_revision: str | None = "a74d9f51bec3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("display_price_cents", sa.Integer(), nullable=True),
        sa.Column("display_currency", sa.String(length=3), nullable=True),
        sa.Column(
            "interval",
            sa.Enum(
                "month",
                "year",
                name="plan_interval",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("interval_count", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("price_cents > 0", name="ck_plans_price_positive"),
        sa.CheckConstraint("interval_count > 0", name="ck_plans_interval_count_positive"),
        sa.CheckConstraint(
            "(display_price_cents IS NULL) = (display_currency IS NULL)",
            name="ck_plans_display_price_pair",
        ),
        sa.CheckConstraint(
            "display_price_cents IS NULL OR display_price_cents > 0",
            name="ck_plans_display_price_positive",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "coupons",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "percent",
                "fixed_cents",
                name="coupon_kind",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column(
            "duration",
            sa.Enum(
                "once",
                "repeating",
                "forever",
                name="coupon_duration",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("duration_periods", sa.Integer(), nullable=True),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("redemptions_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("value > 0", name="ck_coupons_value_positive"),
        sa.CheckConstraint("kind <> 'percent' OR value <= 99", name="ck_coupons_percent_range"),
        sa.CheckConstraint(
            "(kind = 'fixed_cents') = (currency IS NOT NULL)", name="ck_coupons_fixed_currency"
        ),
        sa.CheckConstraint(
            "(duration = 'repeating') = (duration_periods IS NOT NULL)",
            name="ck_coupons_repeating_periods",
        ),
        sa.CheckConstraint(
            "duration_periods IS NULL OR duration_periods > 0",
            name="ck_coupons_duration_periods_positive",
        ),
        sa.CheckConstraint(
            "max_redemptions IS NULL OR max_redemptions > 0",
            name="ck_coupons_max_redemptions_positive",
        ),
        sa.CheckConstraint("redemptions_count >= 0", name="ck_coupons_redemptions_count"),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from", name="ck_coupons_validity_order"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "coupon_plans",
        sa.Column("coupon_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["coupon_id"], ["coupons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("coupon_id", "plan_id"),
    )
    op.create_index(op.f("ix_coupon_plans_plan_id"), "coupon_plans", ["plan_id"], unique=False)

    op.create_table(
        "coupon_redemptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("coupon_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["coupon_id"], ["coupons.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("coupon_id", "user_id", name="uq_coupon_redemptions_coupon_user"),
    )
    op.create_index(
        op.f("ix_coupon_redemptions_coupon_id"), "coupon_redemptions", ["coupon_id"], unique=False
    )
    op.create_index(
        op.f("ix_coupon_redemptions_user_id"), "coupon_redemptions", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_coupon_redemptions_user_id"), table_name="coupon_redemptions")
    op.drop_index(op.f("ix_coupon_redemptions_coupon_id"), table_name="coupon_redemptions")
    op.drop_table("coupon_redemptions")
    op.drop_index(op.f("ix_coupon_plans_plan_id"), table_name="coupon_plans")
    op.drop_table("coupon_plans")
    op.drop_table("coupons")
    op.drop_table("plans")
