"""statistical_suggestions reetiqueta las bandas a los tres estados de salida

Decision de producto del 2026-09-24: el motor tiene tres salidas y nada mas —
SEÑAL FUERTE, SEÑAL MEDIA y SIN SEÑAL— y la banda sale de los mismos umbrales
que la decision. Antes la banda era una escala absoluta de cuatro tramos
(0-39 DEBIL, 40-59 MEDIA, 60-79 FUERTE, 80+ MUY FUERTE) que no coincidia con el
umbral de 60: un NO_BET podia quedar como MEDIA y toda recomendacion era FUERTE.

Backfill solo de datos; el CHECK se ajusta en la migracion siguiente. Las filas
se reetiquetan con lo que ya guardaron:

- `NO_BET` -> `weak` (SIN SEÑAL).
- `RECOMMEND` con score >= max(80, umbral de su variante) -> `strong`.
- el resto de `RECOMMEND` -> `medium`.

El score guardado no se toca: es el que vio el usuario cuando se emitio. El
downgrade es exacto, porque las bandas viejas eran funcion solo del score.

Revision ID: 221b8df05052
Revises: 7c2e9d4a1b58
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "221b8df05052"
down_revision: Union[str, None] = "7c2e9d4a1b58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Piso de SEÑAL FUERTE (`engine.recommendation.STRONG_THRESHOLD`). Copiado y no
#: importado: una migracion no puede cambiar de comportamiento porque el motor
#: cambie despues.
STRONG_THRESHOLD = 80
#: Umbral por defecto de las variantes que no lo declaran en `categories_json`.
DEFAULT_THRESHOLD = 60


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE statistical_suggestions AS s
        SET signal_band = CASE
            WHEN s.decision = 'NO_BET' THEN 'weak'
            WHEN s.signal_score >= GREATEST(
                {STRONG_THRESHOLD},
                COALESCE(
                    (v.categories_json ->> 'recommendation_threshold')::float,
                    {DEFAULT_THRESHOLD}
                )
            ) THEN 'strong'
            ELSE 'medium'
        END
        FROM game_sessions AS g
        JOIN game_variants AS v ON v.id = g.game_variant_id
        WHERE g.id = s.session_id
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE statistical_suggestions
        SET signal_band = CASE
            WHEN signal_score >= 80 THEN 'very_strong'
            WHEN signal_score >= 60 THEN 'strong'
            WHEN signal_score >= 40 THEN 'medium'
            ELSE 'weak'
        END
        """
    )
