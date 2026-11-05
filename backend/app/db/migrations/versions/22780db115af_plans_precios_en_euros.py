"""plans: los precios pasan a euros

Fase 5, paso 5.3. Migracion de datos, sin DDL (decidido el 2026-11-03):
Tipster Page cobra siempre en euros, y se muestra y se cobra un precio fijo.

| Plan | Antes | Ahora |
|---|---|---|
| `mensual` | 100.000 COP | 32 EUR |
| `bimestral` | 150.000 COP | 46 EUR |

No deja fila en `admin_audit_log`: no la hizo un administrador, como las filas
iniciales de los planes.

Se detiene, sin cambiar nada, si encuentra algo que seguiria en pesos y que
la pasarela no podria cobrar:

- una suscripcion `active` o `past_due` en COP (su precio esta congelado y se
  cobraria en pesos). Las del sandbox de Wompi se cancelaron en el paso 5.1;
  una cancelada o vencida no vuelve a cobrar. Una `pending` nunca se pago y
  toma el precio de hoy al abrir el pago siguiente;
- un traslado de precio en COP todavia sin aplicar ni cancelar.

Los cupones de monto fijo en COP no se tocan: dejan de aplicar a los planes en
euros (`currency_mismatch`) y se desactivan desde /admin/descuentos.

El downgrade vuelve a los precios en pesos, si los planes siguen con los
precios que puso esta migracion.

Revision ID: 22780db115af
Revises: 1016ad86ae61
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "22780db115af"
down_revision: str | None = "1016ad86ae61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (codigo, precio en pesos, precio en euros), en centavos.
PRICES = (
    ("mensual", 10_000_000, 3_200),
    ("bimestral", 15_000_000, 4_600),
)


def _count(sql: str) -> int:
    return int(op.get_bind().execute(sa.text(sql)).scalar_one())


def upgrade() -> None:
    live = _count(
        "SELECT count(*) FROM subscriptions "
        "WHERE currency = 'COP' AND status IN ('active', 'past_due')"
    )
    if live:
        raise RuntimeError(
            f"Hay {live} suscripciones activas o en mora en COP: cancelalas desde "
            "/admin/suscripciones antes de pasar los planes a euros"
        )
    pending_changes = _count(
        "SELECT count(*) FROM subscription_price_changes spc "
        "JOIN price_changes pc ON pc.id = spc.price_change_id "
        "WHERE pc.currency = 'COP' AND spc.applied_at IS NULL AND spc.canceled_at IS NULL"
    )
    if pending_changes:
        raise RuntimeError(
            f"Hay {pending_changes} traslados de precio en COP sin aplicar: cancelalos antes"
        )
    for code, _cop, eur in PRICES:
        op.execute(
            sa.text(
                "UPDATE plans SET price_cents = :eur, currency = 'EUR', updated_at = now() "
                "WHERE code = :code"
            ).bindparams(eur=eur, code=code)
        )


def downgrade() -> None:
    for code, cop, eur in PRICES:
        op.execute(
            sa.text(
                "UPDATE plans SET price_cents = :cop, currency = 'COP', updated_at = now() "
                "WHERE code = :code AND currency = 'EUR' AND price_cents = :eur"
            ).bindparams(cop=cop, eur=eur, code=code)
        )
