"""games y game_variants: metadatos de la plataforma multijuego

Fase 4, paso 7 (docs/PLATAFORMA_COMPLETA.md §7.2). Solo DDL. Las columnas que
dependen de cada juego (`slug`, `module`, `icon`, `status`) entran nullables:
las llena el backfill siguiente y la migracion de despues las vuelve
obligatorias y retira `games.active`. `description` y `sort_order` llevan un
valor por defecto constante, que no es una decision sobre los datos.

Revision ID: a3c1e5f7b902
Revises: e3b7d1f9a462
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3c1e5f7b902"
down_revision: str | None = "e3b7d1f9a462"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("games", sa.Column("slug", sa.String(length=60), nullable=True))
    op.add_column("games", sa.Column("module", sa.String(length=32), nullable=True))
    op.add_column(
        "games", sa.Column("description", sa.Text(), server_default="", nullable=False)
    )
    op.add_column("games", sa.Column("icon", sa.String(length=32), nullable=True))
    op.add_column(
        "games", sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("games", sa.Column("status", sa.String(length=16), nullable=True))

    op.add_column(
        "game_variants", sa.Column("description", sa.Text(), server_default="", nullable=False)
    )
    op.add_column(
        "game_variants",
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("game_variants", "sort_order")
    op.drop_column("game_variants", "description")
    op.drop_column("games", "status")
    op.drop_column("games", "sort_order")
    op.drop_column("games", "icon")
    op.drop_column("games", "description")
    op.drop_column("games", "module")
    op.drop_column("games", "slug")
