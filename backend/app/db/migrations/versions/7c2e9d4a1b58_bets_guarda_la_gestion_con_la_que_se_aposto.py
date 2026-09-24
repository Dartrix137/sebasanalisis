"""bets guarda la gestion con la que se aposto

Decision de producto del 2026-09-23: el escalon de una progresion solo avanza
cuando el usuario aposto con esa gestion. Hasta ahora avanzaban las tres con el
cierre de la recomendacion, apostara o no. Para saber cual siguio, la apuesta
guarda su gestion.

Columna nueva y nullable, sin backfill: las apuestas ya registradas no dicen con
que gestion se hicieron, y adivinarlo por el monto seria inventar el dato.

Revision ID: 7c2e9d4a1b58
Revises: b5c04ea1f376
Create Date: 2026-09-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7c2e9d4a1b58"
down_revision: Union[str, None] = "b5c04ea1f376"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bets",
        sa.Column(
            "strategy",
            sa.Enum(
                "flat",
                "martingale",
                "two_sector_recovery",
                name="bet_strategy",
                native_enum=False,
                validate_strings=True,
                create_constraint=True,
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("bets", "strategy")
