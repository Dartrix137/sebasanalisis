"""invoices: lo congelado de cada factura y su emision con Siigo

Fase 5, paso 5.4 (docs/PLATAFORMA_COMPLETA.md §3.17, "Paso 5.4", puntos 3 a 8).
Solo DDL.

- Lo que se congela antes del primer envio: la llave de idempotencia (unica),
  el monto en pesos, las dos tasas con su dia y su fuente, las observaciones,
  la descripcion y una copia de los datos de facturacion del comprador.
- La emision: motivo de espera, intentos, proximo intento, fecha de emision,
  id, nombre y total en Siigo, estado ante la DIAN, CUFE, estado del correo,
  ultimo error y errores de la DIAN.
- `status` pasa a tener su CHECK con los seis estados. Hasta aqui todas las
  filas estan en `pending`, asi que el CHECK se crea sin tocar datos.

Todas las columnas nuevas admiten null (o tienen valor por defecto): las
facturas pendientes que ya hay se preparan al emitirlas.

El downgrade borra las columnas y el CHECK: se pierde lo congelado y el estado
de las facturas ya emitidas (que siguen en Siigo).

Revision ID: a9ce7406f0b4
Revises: 750301b44179
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a9ce7406f0b4"
down_revision: str | None = "750301b44179"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "invoices"
STATUS_CHECK = "invoice_status"

COLUMNS: list[sa.Column] = [
    sa.Column("prepared_at", sa.DateTime(timezone=True)),
    sa.Column("idempotency_key", sa.String(length=30)),
    sa.Column("cop_cents", sa.BigInteger()),
    sa.Column("eur_usd", sa.Numeric(precision=20, scale=10)),
    sa.Column("eur_usd_date", sa.Date()),
    sa.Column("eur_usd_source", sa.String(length=200)),
    sa.Column("usd_cop", sa.Numeric(precision=20, scale=10)),
    sa.Column("usd_cop_date", sa.Date()),
    sa.Column("usd_cop_source", sa.String(length=200)),
    sa.Column("observations", sa.Text()),
    sa.Column("description", sa.String(length=500)),
    sa.Column("buyer_first_names", sa.String(length=50)),
    sa.Column("buyer_last_names", sa.String(length=50)),
    sa.Column("buyer_id_type", sa.String(length=2)),
    sa.Column("buyer_id_number", sa.String(length=20)),
    sa.Column("buyer_email", sa.String(length=255)),
    sa.Column("buyer_country_code", sa.String(length=4)),
    sa.Column("buyer_state_code", sa.String(length=10)),
    sa.Column("buyer_city_code", sa.String(length=10)),
    sa.Column("buyer_address", sa.String(length=256)),
    sa.Column("waiting_reason", sa.String(length=40)),
    sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
    sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
    sa.Column("issue_date", sa.Date()),
    sa.Column("provider_id", sa.String(length=64)),
    sa.Column("provider_name", sa.String(length=40)),
    sa.Column("provider_total", sa.Numeric(precision=18, scale=2)),
    sa.Column("stamp_status", sa.String(length=20)),
    sa.Column("cufe", sa.String(length=200)),
    sa.Column("mail_status", sa.String(length=20)),
    sa.Column("last_error_codes", postgresql.JSONB(astext_type=sa.Text())),
    sa.Column("last_error_message", sa.String(length=500)),
    sa.Column("dian_errors", postgresql.JSONB(astext_type=sa.Text())),
    sa.Column("sent_at", sa.DateTime(timezone=True)),
    sa.Column("accepted_at", sa.DateTime(timezone=True)),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    ),
]


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column(TABLE, column)
    op.create_unique_constraint("invoices_idempotency_key_key", TABLE, ["idempotency_key"])
    op.create_check_constraint(
        STATUS_CHECK,
        TABLE,
        "status IN ('pending', 'sending', 'issued', 'accepted', 'rejected', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint(STATUS_CHECK, TABLE, type_="check")
    op.drop_constraint("invoices_idempotency_key_key", TABLE, type_="unique")
    for column in reversed(COLUMNS):
        op.drop_column(TABLE, column.name)
