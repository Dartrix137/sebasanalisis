"""plans: el plan de dos meses, de 150.000 COP

Fase 4, paso 4 (docs/PLATAFORMA_COMPLETA.md §3.10). Migracion de datos.
Decidido por el usuario el 2026-10-09: ademas del plan mensual hay un plan de
dos meses. Es un plan aparte, no un cupon: un solo cobro de 150.000 COP cada
dos meses (`interval = month`, `interval_count = 2`).

Como el mensual, despues se edita desde /admin/planes, y esta fila inicial no
deja entrada en `admin_audit_log`: no la hizo un administrador.

Revision ID: d2f6a18c4b93
Revises: c95a3b7e2d48
Create Date: 2026-10-09
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2f6a18c4b93"
down_revision: str | None = "c95a3b7e2d48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLAN_CODE = "bimestral"

DESCRIPTION = (
    "Acceso completo a la plataforma durante dos meses, con un solo pago cada dos "
    "meses: registro de mesas de ruleta europea y americana, una recomendación "
    "estadística después de cada giro con su Signal Score, y las tres gestiones de "
    "banca. Las recomendaciones salen del análisis de los resultados que registras: "
    "no son una predicción y no cambian la ventaja de la casa."
)

plans = sa.table(
    "plans",
    sa.column("id", sa.UUID()),
    sa.column("code", sa.String()),
    sa.column("name", sa.String()),
    sa.column("description", sa.Text()),
    sa.column("price_cents", sa.Integer()),
    sa.column("currency", sa.String()),
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
                "name": "Acceso Bimestral",
                "description": DESCRIPTION,
                "price_cents": 15_000_000,
                "currency": "COP",
                "interval": "month",
                "interval_count": 2,
                "active": True,
                # Despues del mensual, que va en 0.
                "sort_order": 1,
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
