"""users: version de sesion y fecha de verificacion del correo

Fase 4, paso 1 (docs/PLATAFORMA_COMPLETA.md §5.2 y §5.3).

- `token_version` viaja en el JWT. Cambiar o restablecer la contrasena la
  incrementa y con eso se invalidan los tokens emitidos antes. Arranca en 0
  para todos: las sesiones abiertas al desplegar siguen valiendo, porque un
  token sin el claim se lee como version 0.
- `email_verified_at` guarda cuando se confirmo el correo. `email_verified` ya
  existia desde el MVP, siempre en False.

Revision ID: 0cef4cd6fadb
Revises: dab3a9ae40f8
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0cef4cd6fadb"
down_revision: str | None = "dab3a9ae40f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
    op.drop_column("users", "email_verified_at")
