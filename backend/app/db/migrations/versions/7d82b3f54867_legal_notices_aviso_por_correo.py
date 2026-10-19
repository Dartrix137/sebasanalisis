"""legal_notices: aviso por correo de una version nueva de un documento legal

Fase 4, paso 9 (docs/PLATAFORMA_COMPLETA.md §6.7). Solo DDL: la tabla
`legal_notices`, una fila por cuenta y por version avisada, escrita cuando el
correo salio. La restriccion unica es la que impide avisar dos veces.

El downgrade borra la tabla: se pierde el registro de a quien se le aviso, y
si el job vuelve a correr con esta tabla de nuevo, avisaria otra vez a quien no
haya aceptado todavia.

Revision ID: 7d82b3f54867
Revises: f4b0d2e6a571
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7d82b3f54867"
down_revision: str | None = "f4b0d2e6a571"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "legal_notices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("legal_document_id", sa.UUID(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["legal_document_id"], ["legal_documents.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "legal_document_id", name="uq_legal_notices_user_document"),
    )
    op.create_index("ix_legal_notices_user_id", "legal_notices", ["user_id"])
    op.create_index("ix_legal_notices_legal_document_id", "legal_notices", ["legal_document_id"])
    op.create_index("ix_legal_notices_sent_at", "legal_notices", ["sent_at"])


def downgrade() -> None:
    op.drop_index("ix_legal_notices_sent_at", table_name="legal_notices")
    op.drop_index("ix_legal_notices_legal_document_id", table_name="legal_notices")
    op.drop_index("ix_legal_notices_user_id", table_name="legal_notices")
    op.drop_table("legal_notices")
