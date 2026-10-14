"""traslado del precio de un plan a sus suscripciones vigentes

Fase 4, paso 6, entrega 3 (docs/PLATAFORMA_COMPLETA.md §4.10 y §10 n.º 5).
Solo DDL: las tablas `price_changes` y `subscription_price_changes`.

El downgrade borra las dos tablas. Los precios que ya se trasladaron siguen en
`subscriptions.price_cents`; solo se pierde el registro de como llegaron ahi.

Revision ID: e3b7d1f9a462
Revises: d9a4c2e7b815
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3b7d1f9a462"
down_revision: str | None = "d9a4c2e7b815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "price_changes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("new_price_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_by_email", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("new_price_cents > 0", name="ck_price_changes_price_positive"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_price_changes_plan_id"), "price_changes", ["plan_id"], unique=False)

    op.create_table(
        "subscription_price_changes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("price_change_id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=False),
        sa.Column("old_price_cents", sa.Integer(), nullable=False),
        sa.Column("new_price_cents", sa.Integer(), nullable=False),
        sa.Column("notice_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_notice_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "old_price_cents > 0", name="ck_subscription_price_changes_old_positive"
        ),
        sa.CheckConstraint(
            "new_price_cents > 0", name="ck_subscription_price_changes_new_positive"
        ),
        sa.CheckConstraint(
            "old_price_cents <> new_price_cents", name="ck_subscription_price_changes_changes"
        ),
        sa.ForeignKeyConstraint(
            ["price_change_id"], ["price_changes.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "price_change_id", "subscription_id", name="uq_subscription_price_changes_pair"
        ),
    )
    op.create_index(
        op.f("ix_subscription_price_changes_price_change_id"),
        "subscription_price_changes",
        ["price_change_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_subscription_price_changes_subscription_id"),
        "subscription_price_changes",
        ["subscription_id"],
        unique=False,
    )
    op.create_index(
        "uq_subscription_price_changes_one_open",
        "subscription_price_changes",
        ["subscription_id"],
        unique=True,
        postgresql_where=sa.text("applied_at IS NULL AND canceled_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_subscription_price_changes_one_open",
        table_name="subscription_price_changes",
        postgresql_where=sa.text("applied_at IS NULL AND canceled_at IS NULL"),
    )
    op.drop_index(
        op.f("ix_subscription_price_changes_subscription_id"),
        table_name="subscription_price_changes",
    )
    op.drop_index(
        op.f("ix_subscription_price_changes_price_change_id"),
        table_name="subscription_price_changes",
    )
    op.drop_table("subscription_price_changes")
    op.drop_index(op.f("ix_price_changes_plan_id"), table_name="price_changes")
    op.drop_table("price_changes")
