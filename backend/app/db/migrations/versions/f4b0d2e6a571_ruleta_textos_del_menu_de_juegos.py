"""ruleta: textos del menu de juegos y orden de sus variantes

Fase 4, paso 7, entrega 2 (docs/PLATAFORMA_COMPLETA.md §7.2). Solo datos.

El menu de juegos muestra la descripcion del juego y la de cada variante. El
seed las pone al crear la ruleta, pero en una base donde la ruleta ya existia
(la del VPS) el seed no vuelve a correr al desplegar (`docs/DESPLIEGUE.md`), y
el backfill de la entrega 1 no las lleno. Sin esto, la tarjeta de la ruleta
saldria sin descripcion y sus variantes sin "37 numeros, con un solo cero".

Solo llena lo que esta vacio, para no pisar lo que un administrador haya
escrito. Los textos son los de `app/db/seed.py`, copiados a proposito: una
migracion no depende del codigo de la aplicacion, que puede cambiar.

El downgrade vacia solo los textos que siguen siendo los que puso el upgrade.
El orden de las variantes no se revierte: antes de esta migracion valia 0 en
las dos y el downgrade no puede saber si lo cambio un administrador.

Revision ID: f4b0d2e6a571
Revises: e2a8c0d4f349
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4b0d2e6a571"
down_revision: str | None = "e2a8c0d4f349"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GAME_DESCRIPTION = (
    "Registra los números de una mesa de ruleta europea o americana y recibe, "
    "después de cada giro, una recomendación estadística para el siguiente."
)
VARIANTS = {
    # nombre: (descripcion, orden)
    "european": ("37 números, con un solo cero.", 0),
    "american": ("38 números, con 0 y 00.", 1),
}


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE games SET description = :d WHERE type = 'roulette' AND description = ''"
        ),
        {"d": GAME_DESCRIPTION},
    )
    for name, (description, order) in VARIANTS.items():
        conn.execute(
            sa.text(
                "UPDATE game_variants v SET description = :d FROM games g "
                "WHERE g.id = v.game_id AND g.type = 'roulette' AND v.name = :n "
                "AND v.description = ''"
            ),
            {"d": description, "n": name},
        )
        conn.execute(
            sa.text(
                "UPDATE game_variants v SET sort_order = :o FROM games g "
                "WHERE g.id = v.game_id AND g.type = 'roulette' AND v.name = :n "
                "AND v.sort_order = 0"
            ),
            {"o": order, "n": name},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE games SET description = '' WHERE type = 'roulette' AND description = :d"),
        {"d": GAME_DESCRIPTION},
    )
    for name, (description, _) in VARIANTS.items():
        conn.execute(
            sa.text(
                "UPDATE game_variants v SET description = '' FROM games g "
                "WHERE g.id = v.game_id AND g.type = 'roulette' AND v.name = :n "
                "AND v.description = :d"
            ),
            {"d": description, "n": name},
        )
