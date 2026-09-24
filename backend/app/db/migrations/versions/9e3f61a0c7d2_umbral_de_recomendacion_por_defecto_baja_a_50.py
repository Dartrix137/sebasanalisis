"""el umbral de recomendacion por defecto baja de 60 a 50

Decision de producto del 2026-09-24: con 60, en mesa real el motor pasaba la
mayoria de los giros en SIN SEÑAL. Con 50 recomienda en ~58% de los giros de
una mesa justa (antes ~35%); FUERTE sigue desde 80, asi que baja su parte dentro
de las recomendaciones (~11%, antes ~18%). La tasa de coincidencia no cambia con
ningun umbral.

Backfill solo de datos: pasa a 50 las variantes que tienen guardado el 60 viejo.
Una variante con otro valor lo tiene porque el admin lo eligio, y se respeta.

Limitacion del downgrade: vuelve a 60 toda variante que este en 50, porque no
hay forma de distinguir las que movio esta migracion de las que el admin ya
habia puesto en 50 a mano.

Revision ID: 9e3f61a0c7d2
Revises: 04569bdd5e59
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "9e3f61a0c7d2"
down_revision: Union[str, None] = "04569bdd5e59"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_DEFAULT = 60
NEW_DEFAULT = 50


def _move(desde: int, hacia: int) -> None:
    op.execute(
        f"""
        UPDATE game_variants
        SET categories_json = jsonb_set(
            categories_json, '{{recommendation_threshold}}', '{hacia}'::jsonb
        )
        WHERE (categories_json ->> 'recommendation_threshold')::float = {desde}
        """
    )


def upgrade() -> None:
    _move(OLD_DEFAULT, NEW_DEFAULT)


def downgrade() -> None:
    _move(NEW_DEFAULT, OLD_DEFAULT)
