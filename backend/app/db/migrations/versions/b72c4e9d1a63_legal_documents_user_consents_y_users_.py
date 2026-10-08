"""legal_documents, user_consents y users.adult_confirmed_at / onboarding_completed_at

Fase 4, paso 2 (docs/PLATAFORMA_COMPLETA.md §6.2 y §6.3).

- `legal_documents`: cada version de cada documento legal. `published_at` null
  es un borrador; una version publicada no se edita.
- `user_consents`: que version exacta acepto cada usuario, cuando, y desde que
  IP y navegador.
- `users.adult_confirmed_at`: la declaracion de mayoria de edad. Queda en null
  para las cuentas que ya existian: no se les inventa una declaracion que no
  hicieron, se les pide al entrar a la mesa.
- `users.onboarding_completed_at`: cuando leyo la pantalla que explica que hace
  y que no hace la plataforma.

Solo DDL. Las versiones iniciales de los documentos van en la migracion
siguiente.

Revision ID: b72c4e9d1a63
Revises: 5a1d7e3b9c42
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b72c4e9d1a63"
down_revision: str | None = "5a1d7e3b9c42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "legal_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "terms",
                "privacy",
                "refunds",
                "cookies",
                name="legal_document_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("requires_acceptance", sa.Boolean(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "version", name="uq_legal_documents_kind_version"),
    )
    op.create_index(op.f("ix_legal_documents_kind"), "legal_documents", ["kind"], unique=False)

    op.create_table(
        "user_consents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("legal_document_id", sa.UUID(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["legal_document_id"], ["legal_documents.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "legal_document_id", name="uq_user_consents_user_document"
        ),
    )
    op.create_index(op.f("ix_user_consents_user_id"), "user_consents", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_user_consents_legal_document_id"),
        "user_consents",
        ["legal_document_id"],
        unique=False,
    )

    op.add_column(
        "users", sa.Column("adult_confirmed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "onboarding_completed_at")
    op.drop_column("users", "adult_confirmed_at")
    op.drop_index(op.f("ix_user_consents_legal_document_id"), table_name="user_consents")
    op.drop_index(op.f("ix_user_consents_user_id"), table_name="user_consents")
    op.drop_table("user_consents")
    op.drop_index(op.f("ix_legal_documents_kind"), table_name="legal_documents")
    op.drop_table("legal_documents")
