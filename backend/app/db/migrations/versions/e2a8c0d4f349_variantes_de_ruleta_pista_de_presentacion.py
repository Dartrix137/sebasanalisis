"""variantes de ruleta: pista de presentacion `display` en categories_json

Fase 4, paso 7 (docs/PLATAFORMA_COMPLETA.md §7.3). Solo datos. Hasta aqui el
frontend pintaba los numeros de rojo, negro o verde buscando a mano la
categoria `color`: era la ultima suposicion de ruleta fuera de los datos. La
pista `display` lo dice en la configuracion, y el motor la ignora.

Solo toca variantes de la ruleta (`games.type = 'roulette'`) que tengan la
categoria `color` con los grupos `red`, `black` y `green`, y que no tengan ya
una pista. La misma configuracion esta en `app/db/seed_data/`.

El downgrade quita la pista de las variantes donde coincide con la que puso
este upgrade.

Revision ID: e2a8c0d4f349
Revises: d0f6b8c2e237
Create Date: 2026-10-14
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2a8c0d4f349"
down_revision: str | None = "d0f6b8c2e237"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DISPLAY = {
    "outcome_tone_category": "color",
    "tones": {"red": "red", "black": "black", "green": "green"},
    "layout": "grid",
    "columns": None,
}


def _roulette_variants(conn: sa.Connection) -> list[sa.Row]:
    return list(
        conn.execute(
            sa.text(
                "SELECT v.id, v.categories_json FROM game_variants v "
                "JOIN games g ON g.id = v.game_id WHERE g.type = 'roulette'"
            )
        ).all()
    )


def upgrade() -> None:
    conn = op.get_bind()
    for variant in _roulette_variants(conn):
        config = variant.categories_json
        if config.get("display") is not None:
            continue
        color = next((c for c in config.get("categories", []) if c.get("id") == "color"), None)
        if color is None or not {"red", "black", "green"} <= set(color.get("groups", {})):
            continue
        config["display"] = DISPLAY
        conn.execute(
            sa.text("UPDATE game_variants SET categories_json = CAST(:c AS JSONB) WHERE id = :id"),
            {"id": variant.id, "c": json.dumps(config)},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for variant in _roulette_variants(conn):
        config = variant.categories_json
        if config.get("display") != DISPLAY:
            continue
        del config["display"]
        conn.execute(
            sa.text("UPDATE game_variants SET categories_json = CAST(:c AS JSONB) WHERE id = :id"),
            {"id": variant.id, "c": json.dumps(config)},
        )
