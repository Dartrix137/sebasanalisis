"""users.guides_seen_at: cuando la cuenta cerro la ventana de las guias

Guias de la ruleta (decididas por el usuario el 2026-11-12). Solo DDL.

La primera vez que una cuenta con acceso entra al inicio le aparece una ventana
con los videos y el PDF de la guia; al cerrarla queda anotada aqui y no vuelve a
salir, tampoco en otro dispositivo. Queda en null para las cuentas que ya
existian: tambien a ellas les aparece una vez.

Revision ID: c3f9a1d7e2b4
Revises: b5e2d8c41f07
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f9a1d7e2b4"
down_revision: str | None = "b5e2d8c41f07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("guides_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "guides_seen_at")
