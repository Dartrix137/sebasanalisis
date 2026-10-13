"""coupon_redemptions: conserva el uso al eliminar la cuenta

Fase 4, paso 5, entrega 3 (docs/PLATAFORMA_COMPLETA.md §5.4 y §3.11). Solo DDL.

`coupon_redemptions.user_id` pasa de `ON DELETE CASCADE` a `SET NULL` y admite
null. Al eliminar una cuenta, el uso del cupon queda sin nada que la
identifique, igual que sus pagos: `coupons.redemptions_count` sigue
coincidiendo con las filas y el tope de usos no se "devuelve".

El downgrade borra los usos que ya quedaron sin cuenta: con la columna
obligatoria no tienen donde quedar.

Revision ID: c8e3a5d7f216
Revises: b6d2f8a1c493
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8e3a5d7f216"
down_revision: str | None = "b6d2f8a1c493"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = "coupon_redemptions_user_id_fkey"


def upgrade() -> None:
    op.drop_constraint(_FK, "coupon_redemptions", type_="foreignkey")
    op.alter_column("coupon_redemptions", "user_id", existing_type=sa.UUID(), nullable=True)
    op.create_foreign_key(
        _FK, "coupon_redemptions", "users", ["user_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.execute("DELETE FROM coupon_redemptions WHERE user_id IS NULL")
    op.drop_constraint(_FK, "coupon_redemptions", type_="foreignkey")
    op.alter_column("coupon_redemptions", "user_id", existing_type=sa.UUID(), nullable=False)
    op.create_foreign_key(
        _FK, "coupon_redemptions", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
