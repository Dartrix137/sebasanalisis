"""subscriptions.payment_source_blocked: la tarjeta que no admite otro intento

Fase 5, paso 5.3b, entrega 3 (decidido por el usuario el 2026-11-17): cuando
la pasarela rechaza un cobro de renovacion sin admitir reintento
(`retry_allowed: false` en Tipster Page; por ejemplo, una tarjeta bloqueada),
no se vuelve a intentar con esa tarjeta: se le pide al cliente que la cambie,
y si no la cambia la suscripcion vence en su fecha. La marca se quita al
guardar otra tarjeta. Solo DDL.

Revision ID: b8d4f2a61c39
Revises: a5c81e3f9d27
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d4f2a61c39"
down_revision: str | None = "a5c81e3f9d27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column(
            "payment_source_blocked",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "payment_source_blocked")
