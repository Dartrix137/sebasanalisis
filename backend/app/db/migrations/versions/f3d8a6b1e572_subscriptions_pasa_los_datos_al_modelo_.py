"""subscriptions: pasa los datos al modelo nuevo

Fase 4, paso 5, entrega 1 (docs/PLATAFORMA_COMPLETA.md §3.2). Migracion de
datos, separada del DDL.

Hasta este paso ninguna pantalla creaba suscripciones, asi que lo esperado es
que la tabla este vacia. Si tiene filas (puestas a mano):

- `plan_id` sale del plan cuyo `code` es el texto que traia la fila;
- el precio y la moneda congelados se toman de ese plan, tal como esta hoy;
- `payment_source_id` recibe lo que habia en `payment_token_ref`.

No inventa nada: si una fila trae un plan que no existe o un estado que el
modelo nuevo no admite, la migracion se detiene y dice cual, para que se
corrija a mano.

Revision ID: f3d8a6b1e572
Revises: e7b1c5a2d904
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3d8a6b1e572"
down_revision: str | None = "e7b1c5a2d904"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("pending", "active", "past_due", "canceled", "expired")


def upgrade() -> None:
    op.execute(
        "UPDATE subscriptions s SET plan_id = p.id, price_cents = p.price_cents, "
        "currency = p.currency FROM plans p WHERE p.code = s.plan_code_legacy"
    )
    op.execute(
        "UPDATE subscriptions SET payment_source_id = payment_token_ref "
        "WHERE payment_token_ref IS NOT NULL"
    )

    conn = op.get_bind()
    sin_plan = conn.execute(
        sa.text("SELECT id, plan_code_legacy FROM subscriptions WHERE plan_id IS NULL")
    ).all()
    if sin_plan:
        detalle = ", ".join(f"{row.id} (plan '{row.plan_code_legacy}')" for row in sin_plan)
        raise RuntimeError(
            "Hay suscripciones cuyo plan no existe en `plans`; corrigelas o borralas "
            f"antes de migrar: {detalle}"
        )
    estados = ", ".join(f"'{s}'" for s in STATUSES)
    mal_estado = conn.execute(
        sa.text(f"SELECT id, status FROM subscriptions WHERE status NOT IN ({estados})")
    ).all()
    if mal_estado:
        detalle = ", ".join(f"{row.id} (estado '{row.status}')" for row in mal_estado)
        raise RuntimeError(
            f"Hay suscripciones con un estado que el modelo nuevo no admite: {detalle}"
        )
    # Mas de una suscripcion viva por cuenta chocaria con el indice unico de la
    # migracion siguiente.
    repetidas = conn.execute(
        sa.text(
            "SELECT user_id FROM subscriptions "
            "WHERE status IN ('pending', 'active', 'past_due') "
            "GROUP BY user_id HAVING count(*) > 1"
        )
    ).all()
    if repetidas:
        detalle = ", ".join(str(row.user_id) for row in repetidas)
        raise RuntimeError(
            "Hay cuentas con mas de una suscripcion pendiente, activa o en mora: " + detalle
        )


def downgrade() -> None:
    op.execute(
        "UPDATE subscriptions s SET plan_code_legacy = p.code "
        "FROM plans p WHERE p.id = s.plan_id"
    )
    op.execute("UPDATE subscriptions SET payment_token_ref = payment_source_id")
