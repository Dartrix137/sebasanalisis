"""statistical_suggestions: SIN SEÑAL pasa de 'weak' a 'none'

Backfill de la decision del 2026-09-24 (SEÑAL DEBIL). Hasta ahora toda fila
'weak' era un NO_BET, es decir SIN SEÑAL; con este cambio 'weak' pasa a
significar SEÑAL DEBIL, asi que esas filas se mueven a 'none'.

Limitacion del downgrade: el esquema anterior no tiene SEÑAL DEBIL. Las
recomendaciones debiles ya guardadas ('weak' con RECOMMEND) bajan como 'medium',
la banda mas baja que alli llevaba recomendacion. El score guardado no cambia.

Revision ID: ccba7ad9d695
Revises: 8d65408c6d06
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "ccba7ad9d695"
down_revision: Union[str, None] = "8d65408c6d06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE statistical_suggestions
        SET signal_band = 'none'
        WHERE signal_band = 'weak' AND decision = 'NO_BET'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE statistical_suggestions
        SET signal_band = CASE WHEN decision = 'RECOMMEND' THEN 'medium' ELSE 'weak' END
        WHERE signal_band IN ('none', 'weak')
        """
    )
