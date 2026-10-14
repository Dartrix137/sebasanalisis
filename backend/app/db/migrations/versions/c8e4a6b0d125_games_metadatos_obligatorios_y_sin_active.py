"""games: metadatos obligatorios; `status` reemplaza a `active`

Fase 4, paso 7 (docs/PLATAFORMA_COMPLETA.md §7.2). Solo DDL: el backfill
anterior ya lleno todas las filas.

`module` acepta `sports`, reservado para las apuestas deportivas (§8.2); que
no se pueda crear un juego con el lo decide el admin, no la base.

El downgrade vuelve a crear `active` a partir de `status`: `active` pasa a
true, y `hidden` y `coming_soon` a false (el esquema anterior no tenia
"proximamente").

Revision ID: c8e4a6b0d125
Revises: b6d2f4a8c013
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8e4a6b0d125"
down_revision: str | None = "b6d2f4a8c013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"

CHECKS = {
    "game_module": "module IN ('discrete_outcome', 'sports')",
    "game_icon": "icon IN ('ruleta', 'dados', 'cartas', 'deportes', 'generico')",
    "game_status": "status IN ('active', 'hidden', 'coming_soon')",
    "ck_games_slug_format": f"slug ~ '{SLUG_PATTERN}'",
}


def upgrade() -> None:
    for column in ("slug", "module", "icon", "status"):
        op.alter_column("games", column, nullable=False)
    op.create_unique_constraint("games_slug_key", "games", ["slug"])
    for name, condition in CHECKS.items():
        op.create_check_constraint(name, "games", condition)
    op.drop_column("games", "active")


def downgrade() -> None:
    op.add_column("games", sa.Column("active", sa.Boolean(), nullable=True))
    op.execute("UPDATE games SET active = (status = 'active')")
    op.alter_column("games", "active", nullable=False)
    for name in CHECKS:
        op.drop_constraint(name, "games", type_="check")
    op.drop_constraint("games_slug_key", "games", type_="unique")
    for column in ("slug", "module", "icon", "status"):
        op.alter_column("games", column, nullable=True)
