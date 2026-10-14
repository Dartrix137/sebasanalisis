"""plan_games: juegos incluidos en cada plan

Fase 4, paso 7 (docs/PLATAFORMA_COMPLETA.md §3.2 y §7.4). Solo DDL. Un plan sin
filas incluye todos los juegos, tambien los que se creen despues; por eso no
hay backfill: los dos planes de hoy quedan sin filas e incluyen todo.

Revision ID: d0f6b8c2e237
Revises: c8e4a6b0d125
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d0f6b8c2e237"
down_revision: str | None = "c8e4a6b0d125"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plan_games",
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("game_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("plan_id", "game_id"),
    )
    op.create_index(op.f("ix_plan_games_game_id"), "plan_games", ["game_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_plan_games_game_id"), table_name="plan_games")
    op.drop_table("plan_games")
