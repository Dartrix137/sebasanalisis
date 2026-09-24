"""signal_band deja de aceptar 'very_strong'

DDL de la decision del 2026-09-24 (tres estados de salida). La migracion
anterior ya reetiqueto las filas, asi que ninguna queda en 'very_strong' y el
CHECK nuevo se puede crear sin tocar datos.

El ancho de la columna (VARCHAR(11)) se deja como esta: el modelo lo fija con
`length=11` para que `alembic check` no vea diferencia.

Revision ID: 04569bdd5e59
Revises: 221b8df05052
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "04569bdd5e59"
down_revision: Union[str, None] = "221b8df05052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "statistical_suggestions"
CONSTRAINT = "signal_band"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(
        CONSTRAINT, TABLE, "signal_band IN ('weak', 'medium', 'strong')"
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(
        CONSTRAINT,
        TABLE,
        "signal_band IN ('weak', 'medium', 'strong', 'very_strong')",
    )
