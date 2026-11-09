"""users.loss_risk_acknowledged_at: la declaracion del riesgo de perdida

Fase 5, paso 5.5 (docs/PLATAFORMA_COMPLETA.md §6.3). Solo DDL.

La cuenta declara, al registrarse, que entiende que las apuestas implican riesgo
de perdida de dinero (decidido por el usuario el 2026-11-09). Queda en null para
las cuentas que ya existian: no se les inventa una declaracion que no hicieron,
se les pide antes de usar la mesa, como la mayoria de edad.

Revision ID: fbce7237bed1
Revises: a9ce7406f0b4
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fbce7237bed1"
down_revision: str | None = "a9ce7406f0b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("loss_risk_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "loss_risk_acknowledged_at")
