"""payment_events: guarda su pasarela (columna nullable)

Fase 5, paso 5.3 (docs/PLATAFORMA_COMPLETA.md §3.19). Solo DDL, primera de
tres, como en el paso 3: esta agrega la columna, `8bb49e212973` la llena y
`1016ad86ae61` la deja obligatoria y pasa la idempotencia a (pasarela, id).

Decidido el 2026-11-03: deja lista la entrada de una segunda pasarela. Cada
aviso queda con su pasarela, y no se procesa dos veces el mismo aviso de una
misma pasarela.

El downgrade quita la columna.

Revision ID: 8281a0c1bd4a
Revises: 5dc9670480c1
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8281a0c1bd4a"
down_revision: str | None = "5dc9670480c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("payment_events", sa.Column("provider", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("payment_events", "provider")
