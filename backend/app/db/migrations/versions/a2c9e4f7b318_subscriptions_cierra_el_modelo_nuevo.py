"""subscriptions: cierra el modelo nuevo

Fase 4, paso 5, entrega 1 (docs/PLATAFORMA_COMPLETA.md §3.2 y §3.4). DDL que
depende de que la migracion anterior ya haya pasado los datos.

- `plan_id`, `price_cents` y `currency` pasan a ser obligatorios.
- `status` gana su CHECK y `price_cents` el suyo.
- Indice unico parcial: una cuenta no tiene dos suscripciones `pending`,
  `active` o `past_due` a la vez. La regla queda en la base, no solo en el codigo.
- Se retiran `plan_code_legacy` (el `plan_id` de texto) y `payment_token_ref`
  (lo reemplaza `payment_source_id`).

Revision ID: a2c9e4f7b318
Revises: f3d8a6b1e572
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2c9e4f7b318"
down_revision: str | None = "f3d8a6b1e572"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LIVE_INDEX = "uq_subscriptions_one_live_per_user"
LIVE_WHERE = "status IN ('pending', 'active', 'past_due')"


def upgrade() -> None:
    op.alter_column("subscriptions", "plan_id", existing_type=sa.UUID(), nullable=False)
    op.alter_column("subscriptions", "price_cents", existing_type=sa.Integer(), nullable=False)
    op.alter_column(
        "subscriptions", "currency", existing_type=sa.String(length=3), nullable=False
    )
    op.create_check_constraint(
        "subscription_status",
        "subscriptions",
        "status IN ('pending', 'active', 'past_due', 'canceled', 'expired')",
    )
    op.create_check_constraint(
        "ck_subscriptions_price_positive", "subscriptions", "price_cents > 0"
    )
    op.create_index(
        LIVE_INDEX,
        "subscriptions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text(LIVE_WHERE),
    )
    op.drop_column("subscriptions", "plan_code_legacy")
    op.drop_column("subscriptions", "payment_token_ref")


def downgrade() -> None:
    op.add_column(
        "subscriptions", sa.Column("payment_token_ref", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "subscriptions", sa.Column("plan_code_legacy", sa.String(length=100), nullable=True)
    )
    op.drop_index(
        LIVE_INDEX, table_name="subscriptions", postgresql_where=sa.text(LIVE_WHERE)
    )
    op.drop_constraint("ck_subscriptions_price_positive", "subscriptions", type_="check")
    op.drop_constraint("subscription_status", "subscriptions", type_="check")
    op.alter_column(
        "subscriptions", "currency", existing_type=sa.String(length=3), nullable=True
    )
    op.alter_column("subscriptions", "price_cents", existing_type=sa.Integer(), nullable=True)
    op.alter_column("subscriptions", "plan_id", existing_type=sa.UUID(), nullable=True)
