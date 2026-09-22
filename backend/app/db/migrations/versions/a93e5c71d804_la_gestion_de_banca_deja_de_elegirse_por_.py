"""la gestion de banca deja de elegirse por sesion: un escalon por progresion

Decision de producto de la Fase 3 (2026-09-22): al crear la mesa el usuario ya
no elige una progresion. La vista de ruleta muestra las tres a la vez —plana,
martingala y recuperacion de dos sectores— con lo que pide cada una, y el
usuario sigue la que quiera. D'Alembert y Fibonacci salen del producto.

Eso deja sin sentido a `strategy_selected`, `strategy_mode` y al escalon unico
`strategy_stage`: ahora cada progresion lleva su propio contador y los tres
avanzan con el mismo cierre de la recomendacion.

**Por que la copia de datos va aqui y no en su propia migracion.** La regla del
proyecto es que los backfills vayan aparte del DDL, y se respeta cuando se trata
de rellenar informacion nueva. Esto no es eso: es mover una columna de sitio.
Separar el ADD, la copia y el DROP en tres revisiones dejaria una revision
intermedia en la que el escalon vive duplicado y otra en la que `alembic
downgrade` a un punto medio pierde el dato. La copia es la mitad que conserva la
informacion del mismo cambio, no un paso independiente.

Las sesiones que estaban en d'Alembert o Fibonacci quedan con los dos contadores
en 0, que es exactamente "progresion plana, escalon 0": ninguno de sus escalones
significa nada en las progresiones que quedan (el escalon 3 de Fibonacci son 3
unidades; en la martingala serian 8).

Revision ID: a93e5c71d804
Revises: f1a7c390b4e2
Create Date: 2026-09-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a93e5c71d804"
down_revision: Union[str, None] = "f1a7c390b4e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- game_sessions: un contador por progresion ---
    op.add_column(
        "game_sessions",
        sa.Column("stage_martingale", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "game_sessions",
        sa.Column("stage_two_sector", sa.Integer(), nullable=False, server_default="0"),
    )
    # La mitad que conserva el dato: el escalon viejo pasa al contador de su
    # progresion. Las demas estrategias se quedan en 0.
    op.execute(
        """
        UPDATE game_sessions
           SET stage_martingale = CASE WHEN strategy_selected = 'martingale'
                                       THEN strategy_stage ELSE 0 END,
               stage_two_sector = CASE WHEN strategy_selected = 'two_sector_recovery'
                                       THEN strategy_stage ELSE 0 END
        """
    )

    # El CHECK ataba el modo a la estrategia; sin esas columnas no aplica.
    op.drop_constraint(
        "ck_session_strategy_mode_matches_strategy", "game_sessions", type_="check"
    )
    op.drop_column("game_sessions", "strategy_selected")
    op.drop_column("game_sessions", "strategy_mode")
    op.drop_column("game_sessions", "strategy_stage")
    op.create_check_constraint(
        "ck_session_stages_not_negative",
        "game_sessions",
        "stage_martingale >= 0 AND stage_two_sector >= 0",
    )

    # --- spins: deshacer un giro restaura los dos escalones ---
    op.add_column(
        "spins", sa.Column("stage_martingale_before", sa.Integer(), nullable=True)
    )
    op.add_column(
        "spins", sa.Column("stage_two_sector_before", sa.Integer(), nullable=True)
    )
    # Los giros existentes traen el escalon de una progresion que ya no se sabe
    # cual era (la columna que lo decia se acaba de ir). Se dejan en NULL, que es
    # lo que `delete_spin` ya interpreta como "no hay escalon que restaurar".
    op.drop_column("spins", "strategy_stage_before")

    for tabla, columnas in (
        ("game_sessions", ("stage_martingale", "stage_two_sector")),
    ):
        for columna in columnas:
            op.alter_column(tabla, columna, server_default=None)


def downgrade() -> None:
    # Vuelve el modelo de una sola progresion por sesion. Es lossy a proposito y
    # conviene saberlo antes de bajarla: de los dos contadores solo sobrevive el
    # de la martingala, porque el esquema viejo no tiene donde poner el otro.
    op.add_column("spins", sa.Column("strategy_stage_before", sa.Integer(), nullable=True))
    op.execute("UPDATE spins SET strategy_stage_before = stage_martingale_before")
    op.drop_column("spins", "stage_two_sector_before")
    op.drop_column("spins", "stage_martingale_before")

    op.drop_constraint("ck_session_stages_not_negative", "game_sessions", type_="check")
    op.add_column(
        "game_sessions",
        sa.Column("strategy_stage", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "game_sessions",
        sa.Column(
            "strategy_selected",
            sa.Enum(
                "flat", "martingale", "dalembert", "fibonacci", "two_sector_recovery",
                name="strategy_selected",
                native_enum=False,
                validate_strings=True,
                create_constraint=True,
            ),
            nullable=False,
            server_default="flat",
        ),
    )
    op.add_column(
        "game_sessions",
        sa.Column(
            "strategy_mode",
            sa.Enum(
                "single", "two_sector",
                name="strategy_mode",
                native_enum=False,
                validate_strings=True,
                create_constraint=True,
            ),
            nullable=False,
            server_default="single",
        ),
    )
    # Se reconstruye la eleccion desde los contadores: si la serie de dos
    # sectores estaba abierta, esa era la que el usuario seguia.
    op.execute(
        """
        UPDATE game_sessions
           SET strategy_selected = CASE
                   WHEN stage_two_sector > 0 THEN 'two_sector_recovery'
                   WHEN stage_martingale > 0 THEN 'martingale'
                   ELSE 'flat' END,
               strategy_mode = CASE
                   WHEN stage_two_sector > 0 THEN 'two_sector' ELSE 'single' END,
               strategy_stage = GREATEST(stage_martingale, stage_two_sector)
        """
    )
    op.create_check_constraint(
        "ck_session_strategy_mode_matches_strategy",
        "game_sessions",
        "(strategy_mode = 'two_sector') = (strategy_selected = 'two_sector_recovery')",
    )
    op.drop_column("game_sessions", "stage_two_sector")
    op.drop_column("game_sessions", "stage_martingale")

    for columna in ("strategy_selected", "strategy_mode", "strategy_stage"):
        op.alter_column("game_sessions", columna, server_default=None)
