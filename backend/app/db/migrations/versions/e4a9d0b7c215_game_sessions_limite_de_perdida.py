"""game_sessions: limite de perdida por sesion

El documento de estrategia verificado (§9) pide fijar un limite de perdida antes
de jugar. Hasta ahora las alertas de banca lo aproximaban con umbrales fijos
sobre la banca inicial; con esta columna cada sesion guarda el del usuario.

Revision ID: e4a9d0b7c215
Revises: c8b3e21f47a9
Create Date: 2026-09-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4a9d0b7c215"
down_revision: Union[str, None] = "c8b3e21f47a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable: las sesiones existentes no tienen limite y siguen con las
    # alertas por defecto.
    op.add_column(
        "game_sessions", sa.Column("loss_limit", sa.Numeric(14, 2), nullable=True)
    )
    op.create_check_constraint(
        "ck_session_loss_limit_within_bankroll",
        "game_sessions",
        "loss_limit IS NULL OR (loss_limit > 0 AND loss_limit <= bankroll_start)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_session_loss_limit_within_bankroll", "game_sessions", type_="check"
    )
    op.drop_column("game_sessions", "loss_limit")
