"""subscriptions.provider_subscription_id: la suscripcion del lado de la pasarela

Fase 5, paso 5.3b (decidido por el usuario el 2026-11-17): la renovacion
automatica con las suscripciones de Tipster Page (Solidgate). Cada cobro de una
renovacion se hace contra una suscripcion que vive en la pasarela, con su
propio id, distinto del medio de pago guardado (`payment_source_id`). Solo DDL.

Revision ID: a5c81e3f9d27
Revises: d7a2e5c9f1b3
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a5c81e3f9d27"
down_revision: str | None = "d7a2e5c9f1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscriptions", sa.Column("provider_subscription_id", sa.String(length=255), nullable=True)
    )
    # El aviso de la pasarela trae su id: con el se encuentra la suscripcion.
    op.create_index(
        "ix_subscriptions_provider_subscription_id",
        "subscriptions",
        ["provider_subscription_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_subscriptions_provider_subscription_id", table_name="subscriptions")
    op.drop_column("subscriptions", "provider_subscription_id")
