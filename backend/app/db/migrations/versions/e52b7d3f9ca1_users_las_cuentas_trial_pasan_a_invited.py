"""users: las cuentas 'trial' pasan a 'invited' sin vencimiento

Fase 4, paso 3. Backfill, separado del DDL (docs/PLATAFORMA_COMPLETA.md §2.3).

Decision del usuario del 2026-10-08 (§10 n.º 1): las cuentas que ya existian
como `trial` conservan la mesa. Pasan a `invited` con `access_expires_at` en
null, es decir sin vencimiento; el administrador les retira el acceso a mano
cuando exista el pago. No se les envia correo.

Limitacion del downgrade: despues de subir, una cuenta `invited` que viene de
`trial` no se distingue de una invitada por un administrador. El downgrade no
toca filas: quedan como `invited`, que el esquema anterior tambien acepta.

Revision ID: e52b7d3f9ca1
Revises: d41a6c2e8b90
Create Date: 2026-10-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e52b7d3f9ca1"
down_revision: str | None = "d41a6c2e8b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE users SET access_type = 'invited', access_expires_at = NULL "
        "WHERE access_type = 'trial'"
    )


def downgrade() -> None:
    pass
