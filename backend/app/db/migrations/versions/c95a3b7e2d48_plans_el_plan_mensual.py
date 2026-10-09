"""plans: el plan unico, mensual, de 100.000 COP

Fase 4, paso 4 (docs/PLATAFORMA_COMPLETA.md §3.10). Migracion de datos,
separada del DDL. Decidido por el usuario el 2026-10-09: el plan lo siembra una
migracion y despues se edita desde /admin/planes.

- Se cobran 100.000 COP al mes (`price_cents` va en centavos).
- Los 30 USD son el precio de presentacion: solo visual, una cifra fija que no
  sale de una tasa de cambio y nunca se usa para cobrar.

No deja fila en `admin_audit_log`: no lo hizo un administrador.

Revision ID: c95a3b7e2d48
Revises: b84f2a6d1c37
Create Date: 2026-10-09
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c95a3b7e2d48"
down_revision: str | None = "b84f2a6d1c37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLAN_CODE = "mensual"

DESCRIPTION = (
    "Acceso completo a la plataforma durante un mes: registro de mesas de ruleta "
    "europea y americana, una recomendación estadística después de cada giro con su "
    "Signal Score, y las tres gestiones de banca. Las recomendaciones salen del "
    "análisis de los resultados que registras: no son una predicción y no cambian "
    "la ventaja de la casa."
)

plans = sa.table(
    "plans",
    sa.column("id", sa.UUID()),
    sa.column("code", sa.String()),
    sa.column("name", sa.String()),
    sa.column("description", sa.Text()),
    sa.column("price_cents", sa.Integer()),
    sa.column("currency", sa.String()),
    sa.column("display_price_cents", sa.Integer()),
    sa.column("display_currency", sa.String()),
    sa.column("interval", sa.String()),
    sa.column("interval_count", sa.Integer()),
    sa.column("active", sa.Boolean()),
    sa.column("sort_order", sa.Integer()),
)


def upgrade() -> None:
    op.bulk_insert(
        plans,
        [
            {
                "id": uuid.uuid4(),
                "code": PLAN_CODE,
                "name": "Acceso Mensual",
                "description": DESCRIPTION,
                "price_cents": 10_000_000,
                "currency": "COP",
                "display_price_cents": 3_000,
                "display_currency": "USD",
                "interval": "month",
                "interval_count": 1,
                "active": True,
                "sort_order": 0,
            }
        ],
    )


def downgrade() -> None:
    # Los cupones limitados a este plan dejan de estarlo; sin esto la llave
    # RESTRICT de coupon_plans no dejaria borrarlo.
    op.execute(
        "DELETE FROM coupon_plans WHERE plan_id IN "
        f"(SELECT id FROM plans WHERE code = '{PLAN_CODE}')"
    )
    op.execute(f"DELETE FROM plans WHERE code = '{PLAN_CODE}'")
