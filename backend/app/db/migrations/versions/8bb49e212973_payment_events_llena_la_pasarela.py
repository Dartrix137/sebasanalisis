"""payment_events: llena la pasarela de los eventos que ya habia

Fase 5, paso 5.3. Migracion de datos, segunda de tres (ver `8281a0c1bd4a`).

De donde sale la pasarela de cada fila, sin inventar nada:

1. El prefijo de `provider_event_id`. Todo id lo lleva desde el primer
   webhook (paso 5 de la Fase 4): `wompi:<checksum>`, `wompi:invalid:...`,
   `fake:...`, `none:invalid:...`. Se reviso en cada version de
   `payments/wompi.py` del historial.
2. Un id sin prefijo no deberia existir. Si aparece, es de antes del paso 5.1,
   cuando la unica pasarela era Wompi (solo con llaves de sandbox).

El downgrade vacia la columna.

Revision ID: 8bb49e212973
Revises: 8281a0c1bd4a
Create Date: 2026-11-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "8bb49e212973"
down_revision: str | None = "8281a0c1bd4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE payment_events
        SET provider = CASE
            WHEN position(':' in provider_event_id) > 0
                THEN left(split_part(provider_event_id, ':', 1), 50)
            ELSE 'wompi'
        END
        WHERE provider IS NULL
        """
    )


def downgrade() -> None:
    op.execute("UPDATE payment_events SET provider = NULL")
