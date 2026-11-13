"""invoices.cancel_reason: el motivo `test_payment`

Las facturas de los pagos de prueba (Fase 5, paso 5.6; decidido por el usuario
el 2026-11-13). Solo DDL: amplia el CHECK de `cancel_reason`.

Nada distingue un pago del sandbox de Tipster Page de uno real: los pagos de
prueba aprobados en el VPS tienen su factura `pending`, y con
`INVOICE_ISSUER=siigo` en la empresa real saldrian a la DIAN como facturas de
verdad. `scripts/cancel_test_invoices.py` (`core/sandbox_payments.py`) las aparta con este motivo antes de
encender la emision.

Revision ID: d7a2e5c9f1b3
Revises: c3f9a1d7e2b4
Create Date: 2026-11-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d7a2e5c9f1b3"
down_revision: str | None = "c3f9a1d7e2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REASONS = "('refunded', 'voided', 'annulled_in_siigo', 'test_payment')"
OLD_REASONS = "('refunded', 'voided', 'annulled_in_siigo')"


def upgrade() -> None:
    op.drop_constraint("invoice_cancel_reason", "invoices", type_="check")
    op.create_check_constraint(
        "invoice_cancel_reason", "invoices", f"cancel_reason IN {REASONS}"
    )


def downgrade() -> None:
    op.drop_constraint("invoice_cancel_reason", "invoices", type_="check")
    # La factura sigue `cancelled` (no se emite), sin motivo: el CHECK viejo no
    # conoce `test_payment` y un null lo pasa.
    op.execute("UPDATE invoices SET cancel_reason = NULL WHERE cancel_reason = 'test_payment'")
    op.create_check_constraint(
        "invoice_cancel_reason", "invoices", f"cancel_reason IN {OLD_REASONS}"
    )
