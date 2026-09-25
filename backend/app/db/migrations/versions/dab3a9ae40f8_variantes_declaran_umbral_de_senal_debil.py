"""las variantes declaran el umbral de señal debil (35)

Backfill de la decision del 2026-09-24: `categories_json.weak_threshold` es el
piso de SEÑAL DEBIL y el minimo para recomendar algo. Se agrega con 35 a las
variantes que no lo tienen, sin pasar nunca por encima de su umbral medio
(`recommendation_threshold`): si el admin lo habia bajado de 35, el debil queda
igual al medio y la banda DEBIL no aparece en esa variante.

El motor lee 35 por defecto aunque la clave falte; guardarla hace que el admin
la vea y la pueda editar.

Revision ID: dab3a9ae40f8
Revises: ccba7ad9d695
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "dab3a9ae40f8"
down_revision: Union[str, None] = "ccba7ad9d695"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_WEAK = 35
DEFAULT_MEDIUM = 50


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE game_variants
        SET categories_json = jsonb_set(
            categories_json,
            '{{weak_threshold}}',
            to_jsonb(LEAST(
                {DEFAULT_WEAK},
                COALESCE(
                    (categories_json ->> 'recommendation_threshold')::float,
                    {DEFAULT_MEDIUM}
                )
            ))
        )
        WHERE NOT categories_json ? 'weak_threshold'
        """
    )


def downgrade() -> None:
    op.execute(
        "UPDATE game_variants SET categories_json = categories_json - 'weak_threshold'"
    )
