"""statistical_suggestions guarda la recomendacion del motor y como cerro

Hasta el MVP la tabla estaba creada y **vacia a proposito**: los endpoints
recalculaban desde los giros en cada llamada. La Fase 3 la empieza a escribir,
una fila por recomendacion emitida, porque `outcome` y `resolved_spin_id` son
hechos del pasado que no se pueden re-simular: dependen de que recomendo el
motor con la formula de ese momento, no con la de hoy.

§3.3 del documento de arquitectura pedia alinear la tabla con el contrato de la
API **antes** de escribir la primera fila. Esta migracion lo hace:

- `chi_square_pvalue` -> `chi_square_pvalue_adjusted`: lo que se expone y lo que
  sostiene la decision es el p-valor ya corregido por comparaciones multiples
  (§2.4), nunca el crudo.
- se agregan `observed_ci_low` / `observed_ci_high`, que la API ya devolvia y la
  tabla no tenia (§2.2).

Se retiran `significance_score`, `strength` e `is_top3`: describian el ranking
top-3, que desde la Fase 3 deja de ser lo que esta tabla registra. `signal_score`
y `signal_band` ocupan su lugar. La tabla esta vacia, asi que no hay datos que
migrar — el DROP no pierde nada.

Revision ID: f1a7c390b4e2
Revises: e4a9d0b7c215
Create Date: 2026-09-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "f1a7c390b4e2"
down_revision: Union[str, None] = "e4a9d0b7c215"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "statistical_suggestions"

# Los enums del proyecto se materializan como VARCHAR + CHECK, no como tipo
# nativo de PostgreSQL (ver `app.models.base.enum_col`): asi agregar un valor
# nuevo no obliga a un ALTER TYPE.
DECISIONS = ("RECOMMEND", "NO_BET")
SIGNAL_BANDS = ("weak", "medium", "strong", "very_strong")
OUTCOMES = ("PENDING", "HIT", "MISS")


def _enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(
        *values,
        name=name,
        native_enum=False,
        validate_strings=True,
        create_constraint=True,
    )


def upgrade() -> None:
    # --- Alineacion pendiente de §3.3, antes de la primera fila ---
    op.alter_column(
        TABLE, "chi_square_pvalue", new_column_name="chi_square_pvalue_adjusted"
    )
    op.add_column(TABLE, sa.Column("observed_ci_low", sa.Float(), nullable=False,
                                   server_default="0"))
    op.add_column(TABLE, sa.Column("observed_ci_high", sa.Float(), nullable=False,
                                   server_default="1"))

    # --- Lo que describia el ranking top-3 y ya no aplica ---
    op.drop_column(TABLE, "significance_score")
    op.drop_column(TABLE, "strength")
    op.drop_column(TABLE, "is_top3")

    # --- La recomendacion ---
    op.add_column(
        TABLE,
        sa.Column("decision", _enum(*DECISIONS, name="recommendation_decision"),
                  nullable=False, server_default="NO_BET"),
    )
    op.add_column(TABLE, sa.Column("market_key", sa.String(80), nullable=False,
                                   server_default=""))
    op.add_column(TABLE, sa.Column("signal_score", sa.Float(), nullable=False,
                                   server_default="0"))
    op.add_column(
        TABLE,
        sa.Column("signal_band", _enum(*SIGNAL_BANDS, name="signal_band"),
                  nullable=False, server_default="weak"),
    )
    # Dinero en enteros (centavos), nunca float. Null con NO_BET: no hay nada
    # que apostar.
    op.add_column(TABLE, sa.Column("stake_cents", sa.Integer(), nullable=True))
    op.add_column(TABLE, sa.Column("currency", sa.String(3), nullable=False,
                                   server_default="COP"))
    op.add_column(
        TABLE,
        sa.Column("outcome", _enum(*OUTCOMES, name="recommendation_outcome"),
                  nullable=False, server_default="PENDING"),
    )
    op.add_column(
        TABLE, sa.Column("resolved_spin_id", UUID(as_uuid=True),
                         nullable=True)
    )
    op.create_foreign_key(
        "fk_statistical_suggestions_resolved_spin_id_spins",
        TABLE, "spins", ["resolved_spin_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(
        "ix_statistical_suggestions_resolved_spin_id", TABLE, ["resolved_spin_id"]
    )

    # `option_label` guarda ahora la etiqueta del mercado ("Docena: 1a + 2a
    # docena"), mas larga que la de un grupo suelto.
    op.alter_column(TABLE, "option_label", type_=sa.String(80),
                    existing_type=sa.String(60), existing_nullable=False)

    # Los server_default existen solo para poder agregar columnas NOT NULL sobre
    # una tabla que podria no estar vacia. La aplicacion siempre escribe estos
    # valores, asi que se retiran para que un INSERT incompleto falle en vez de
    # guardar un "NO_BET weak" silencioso.
    for columna in ("observed_ci_low", "observed_ci_high", "decision", "market_key",
                    "signal_score", "signal_band"):
        op.alter_column(TABLE, columna, server_default=None)


def downgrade() -> None:
    op.alter_column(TABLE, "option_label", type_=sa.String(60),
                    existing_type=sa.String(80), existing_nullable=False)

    op.drop_index("ix_statistical_suggestions_resolved_spin_id", table_name=TABLE)
    op.drop_constraint(
        "fk_statistical_suggestions_resolved_spin_id_spins", TABLE, type_="foreignkey"
    )
    for columna in ("resolved_spin_id", "outcome", "currency", "stake_cents",
                    "signal_band", "signal_score", "market_key", "decision"):
        op.drop_column(TABLE, columna)

    # Se restauran con server_default por el mismo motivo que arriba: la tabla
    # podria tener filas de Fase 3 que no traen estos valores.
    op.add_column(TABLE, sa.Column("significance_score", sa.Float(), nullable=False,
                                   server_default="0"))
    op.add_column(
        TABLE,
        sa.Column(
            "strength",
            _enum("strong", "medium", "weak", name="signal_strength"),
            nullable=False,
            server_default="weak",
        ),
    )
    op.add_column(TABLE, sa.Column("is_top3", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))
    for columna in ("significance_score", "strength", "is_top3"):
        op.alter_column(TABLE, columna, server_default=None)

    op.drop_column(TABLE, "observed_ci_high")
    op.drop_column(TABLE, "observed_ci_low")
    op.alter_column(
        TABLE, "chi_square_pvalue_adjusted", new_column_name="chi_square_pvalue"
    )
