"""spins guarda el escalon previo, para poder deshacer un giro sin perder dinero

Deshacer un giro que ya resolvio apuestas tiene que devolver la sesion al estado
anterior: la banca, el escalon de la progresion y las apuestas. El escalon no se
puede recalcular hacia atras — `advance_stage` no es invertible, y replicar la
partida entera pisaria un "reiniciar progresion" hecho a mano —, asi que cada
giro guarda el escalon que habia antes de resolverse.

Revision ID: c8b3e21f47a9
Revises: a1f4c07b93de
Create Date: 2026-09-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8b3e21f47a9"
down_revision: Union[str, None] = "a1f4c07b93de"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable a proposito: los giros ya registrados no lo tienen, y al
    # deshacerlos simplemente no se restaura ningun escalon.
    op.add_column(
        "spins", sa.Column("strategy_stage_before", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("spins", "strategy_stage_before")
