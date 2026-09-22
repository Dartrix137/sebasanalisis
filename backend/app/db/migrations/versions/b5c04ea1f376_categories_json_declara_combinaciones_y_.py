"""categories_json declara combinaciones permitidas, umbral y mercados

Migracion de DATOS, sin DDL: `categories_json` es JSONB y su forma no esta en el
schema. Va separada del DDL de la Fase 3 a proposito (regla de migraciones de
CLAUDE.md y peticion explicita del alcance de esta fase).

Agrega a cada variante de ruleta ya sembrada tres cosas que el motor de
recomendacion lee de los datos y nunca hardcodea (§2.10):

- `allowed_combinations`: las parejas de grupos de pago 2:1 dentro de una misma
  categoria (dos docenas, dos columnas). Es un ARRAY y no un objeto porque JSONB
  no conserva el orden de las claves de un objeto, y el desempate del motor
  necesita un orden de catalogo estable.
- `recommendation_threshold`: el `signal_score` a partir del cual se recomienda
  apostar. 60 por defecto, editable por variante desde el admin.
- `market: false` en el grupo verde: el 0 y el 00 no son una zona que el producto
  recomiende. El grupo se conserva porque lo necesitan las frecuencias de color
  (para que sumen 1) y el chi-cuadrado (para tener todas sus celdas).

Solo toca variantes que reconoce por su estructura: las que tienen grupos de
pago 2:1 agrupables. Una variante de otro juego que alguien haya creado desde el
admin se queda como esta, y el motor la lee igual — sin `allowed_combinations`
simplemente no tiene mercados combinados.

Revision ID: b5c04ea1f376
Revises: a93e5c71d804
Create Date: 2026-09-22
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b5c04ea1f376"
down_revision: Union[str, None] = "a93e5c71d804"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_THRESHOLD = 60

#: Etiquetas de las parejas conocidas de ruleta. Una categoria que no este aqui
#: cae al nombre generado, que sigue siendo legible.
LABELS = {
    ("dozen", "first", "second"): "1ª + 2ª docena",
    ("dozen", "first", "third"): "1ª + 3ª docena",
    ("dozen", "second", "third"): "2ª + 3ª docena",
    ("column", "first", "second"): "1ª + 2ª columna",
    ("column", "first", "third"): "1ª + 3ª columna",
    ("column", "second", "third"): "2ª + 3ª columna",
}


def _combinations_for(config: dict) -> list[dict]:
    """Parejas de grupos de pago 2:1 dentro de cada categoria.

    El orden —categorias en el orden del array, grupos por id alfabetico— es el
    mismo que usa `engine.recommendation.market_catalog`, para que el catalogo
    guardado y el calculado coincidan.
    """
    salida: list[dict] = []
    for cat in config.get("categories", []):
        ids = sorted(g for g, v in cat.get("groups", {}).items() if v.get("payout") == 2)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                etiqueta = LABELS.get(
                    (cat["id"], a, b),
                    f"{cat['groups'][a].get('label', a)} + {cat['groups'][b].get('label', b)}",
                )
                salida.append(
                    {
                        "id": f"{cat['id']}:{a}+{b}",
                        "label": etiqueta,
                        "category_id": cat["id"],
                        "group_ids": [a, b],
                    }
                )
    return salida


def upgrade() -> None:
    conn = op.get_bind()
    filas = conn.execute(
        sa.text("SELECT id, categories_json FROM game_variants")
    ).fetchall()

    for variant_id, config in filas:
        if not isinstance(config, dict):
            continue
        combinaciones = _combinations_for(config)
        if not combinaciones:
            # Nada que agrupar: no es una variante con apuestas de pago 2:1.
            continue

        nuevo = dict(config)
        nuevo["allowed_combinations"] = combinaciones
        nuevo.setdefault("recommendation_threshold", DEFAULT_THRESHOLD)

        categorias = []
        for cat in nuevo.get("categories", []):
            cat = dict(cat)
            grupos = {}
            for gid, grupo in cat.get("groups", {}).items():
                grupo = dict(grupo)
                # El verde de la ruleta: cubre el 0/00 y paga como pleno o como
                # split, no es una zona recomendable.
                if gid == "green":
                    grupo["market"] = False
                grupos[gid] = grupo
            cat["groups"] = grupos
            categorias.append(cat)
        nuevo["categories"] = categorias

        conn.execute(
            sa.text(
                "UPDATE game_variants SET categories_json = CAST(:cfg AS jsonb) "
                "WHERE id = :id"
            ),
            {"cfg": json.dumps(nuevo, ensure_ascii=False), "id": variant_id},
        )


def downgrade() -> None:
    """Quita las tres claves de la Fase 3 y deja `categories_json` como estaba.

    Es reversible de verdad porque no se perdio nada al subir: las tres claves se
    agregaron sin tocar `possible_outcomes` ni la composicion de los grupos.
    """
    conn = op.get_bind()
    filas = conn.execute(
        sa.text("SELECT id, categories_json FROM game_variants")
    ).fetchall()

    for variant_id, config in filas:
        if not isinstance(config, dict):
            continue
        nuevo = {
            k: v
            for k, v in config.items()
            if k not in ("allowed_combinations", "recommendation_threshold")
        }
        categorias = []
        for cat in nuevo.get("categories", []):
            cat = dict(cat)
            cat["groups"] = {
                gid: {k: v for k, v in grupo.items() if k != "market"}
                for gid, grupo in cat.get("groups", {}).items()
            }
            categorias.append(cat)
        nuevo["categories"] = categorias

        conn.execute(
            sa.text(
                "UPDATE game_variants SET categories_json = CAST(:cfg AS jsonb) "
                "WHERE id = :id"
            ),
            {"cfg": json.dumps(nuevo, ensure_ascii=False), "id": variant_id},
        )
