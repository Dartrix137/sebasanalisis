"""signal_band acepta 'none' para SIN SEÑAL

Decision de producto del 2026-09-24: aparece SEÑAL DEBIL (score entre el umbral
debil, 35, y el medio, 50), que recomienda solo la apuesta base. Pasa a ser
'weak', el nombre que le corresponde, y SIN SEÑAL deja de usarlo y pasa a
'none'.

Solo DDL: el CHECK admite 'none' ademas de los tres valores actuales. Las filas
se reetiquetan en la migracion siguiente.

Revision ID: 8d65408c6d06
Revises: 9e3f61a0c7d2
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "8d65408c6d06"
down_revision: Union[str, None] = "9e3f61a0c7d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "statistical_suggestions"
CONSTRAINT = "signal_band"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(
        CONSTRAINT, TABLE, "signal_band IN ('none', 'weak', 'medium', 'strong')"
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(
        CONSTRAINT, TABLE, "signal_band IN ('weak', 'medium', 'strong')"
    )
