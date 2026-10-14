"""games: backfill de slug, modulo, icono y estado

Fase 4, paso 7 (docs/PLATAFORMA_COMPLETA.md §7.2). Solo datos, separado del DDL.
Decisiones del usuario del 2026-10-14:

- Todo juego que ya existe es de resultados discretos (`discrete_outcome`).
- `active = true` pasa a `status = 'active'`; `false`, a `'hidden'`.
- La ruleta (`type = 'roulette'`) lleva el slug `ruleta` y el icono `ruleta`.
  Cualquier otro juego toma el slug de su `type` (minusculas, guiones) y el
  icono generico. Si dos quedaran con el mismo slug, el segundo lleva un sufijo.

Las sesiones no se tocan: llegan a su juego por la variante, asi que las mesas
abiertas de hoy siguen siendo de ruleta sin cambiar nada.

El downgrade deja las columnas en null; la migracion anterior las retira.

Revision ID: b6d2f4a8c013
Revises: a3c1e5f7b902
Create Date: 2026-10-14
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6d2f4a8c013"
down_revision: str | None = "a3c1e5f7b902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROULETTE_TYPE = "roulette"
ROULETTE_SLUG = "ruleta"


def _slug_from_type(game_type: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", game_type.lower()).strip("-")
    return slug[:50] or "juego"


def upgrade() -> None:
    conn = op.get_bind()
    games = conn.execute(
        sa.text("SELECT id, type, active FROM games ORDER BY created_at, id")
    ).all()

    # La ruleta reserva su slug primero, para que ningun otro juego se lo quede.
    games = sorted(games, key=lambda g: g.type != ROULETTE_TYPE)
    taken: set[str] = set()
    for game in games:
        is_roulette = game.type == ROULETTE_TYPE
        base = ROULETTE_SLUG if is_roulette else _slug_from_type(game.type)
        slug, n = base, 2
        while slug in taken:
            slug, n = f"{base}-{n}", n + 1
        taken.add(slug)
        conn.execute(
            sa.text(
                "UPDATE games SET slug = :slug, module = 'discrete_outcome', "
                "icon = :icon, status = :status WHERE id = :id"
            ),
            {
                "id": game.id,
                "slug": slug,
                "icon": "ruleta" if is_roulette else "generico",
                "status": "active" if game.active else "hidden",
            },
        )


def downgrade() -> None:
    op.execute("UPDATE games SET slug = NULL, module = NULL, icon = NULL, status = NULL")
