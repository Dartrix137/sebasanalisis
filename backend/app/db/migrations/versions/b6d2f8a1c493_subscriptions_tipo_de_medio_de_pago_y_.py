"""subscriptions: tipo del medio de pago guardado y aviso enviado

Fase 4, paso 5, entrega 2 (docs/PLATAFORMA_COMPLETA.md §3.5 y §3.8). Solo DDL.

- `payment_source_type`: `CARD` o `NEQUI`. Hace falta al cobrar: las cuotas
  solo se mandan si la fuente es una tarjeta.
- `notice_sent_for`: el `current_period_end` del periodo cuyo aviso por correo
  ya se envio (el del cobro automatico, o el de vencimiento en el pago manual).
  Es lo que hace que el aviso salga una sola vez por periodo aunque el job
  corra cada hora.

Revision ID: b6d2f8a1c493
Revises: a2c9e4f7b318
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6d2f8a1c493"
down_revision: str | None = "a2c9e4f7b318"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscriptions", sa.Column("payment_source_type", sa.String(length=16), nullable=True)
    )
    op.add_column(
        "subscriptions",
        sa.Column("notice_sent_for", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "notice_sent_for")
    op.drop_column("subscriptions", "payment_source_type")
