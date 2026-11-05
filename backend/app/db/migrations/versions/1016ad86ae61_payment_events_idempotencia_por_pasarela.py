"""payment_events: idempotencia por (pasarela, id de evento)

Fase 5, paso 5.3. Solo DDL, tercera de tres (ver `8281a0c1bd4a`).

- `provider` pasa a obligatoria.
- La unicidad deja de ser solo `provider_event_id` y pasa a ser
  (`provider`, `provider_event_id`): `uq_payment_events_provider_event`.

El downgrade vuelve a la unicidad por `provider_event_id` sola, con el nombre
que Postgres le dio en el schema inicial. No falla con los datos de hoy: todos
los ids llevan el prefijo de su pasarela, asi que no se repiten entre
pasarelas. La columna vuelve a nullable; la quita `8281a0c1bd4a`.

Revision ID: 1016ad86ae61
Revises: 8bb49e212973
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1016ad86ae61"
down_revision: str | None = "8bb49e212973"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# El que le puso Postgres a `sa.UniqueConstraint('provider_event_id')` en el
# schema inicial (`d362196dee55`), sin nombre explicito.
OLD_UNIQUE = "payment_events_provider_event_id_key"
NEW_UNIQUE = "uq_payment_events_provider_event"


def upgrade() -> None:
    op.alter_column(
        "payment_events", "provider", existing_type=sa.String(length=50), nullable=False
    )
    op.drop_constraint(OLD_UNIQUE, "payment_events", type_="unique")
    op.create_unique_constraint(NEW_UNIQUE, "payment_events", ["provider", "provider_event_id"])


def downgrade() -> None:
    op.drop_constraint(NEW_UNIQUE, "payment_events", type_="unique")
    op.create_unique_constraint(OLD_UNIQUE, "payment_events", ["provider_event_id"])
    op.alter_column(
        "payment_events", "provider", existing_type=sa.String(length=50), nullable=True
    )
