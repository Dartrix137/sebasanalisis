"""admin_audit_log: bitacora de acciones de administradores

Fase 4, paso 3 (docs/PLATAFORMA_COMPLETA.md §4.6; se crea aqui y no en el paso
6 por la precision de §9). Toda accion de admin sobre acceso, dinero, planes,
cupones o documentos legales deja una fila, en la misma transaccion que el
cambio. No tiene endpoint de borrado.

`admin_user_id` es SET NULL: si el administrador elimina su cuenta, lo que hizo
sigue en la bitacora.

Revision ID: a74d9f51bec3
Revises: f63c8e40adb2
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a74d9f51bec3"
down_revision: str | None = "f63c8e40adb2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("admin_user_id", sa.UUID(), nullable=True),
        sa.Column("admin_email", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["admin_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_admin_audit_log_created_at"), "admin_audit_log", ["created_at"], unique=False
    )
    op.create_index(
        "ix_admin_audit_log_target", "admin_audit_log", ["target_type", "target_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_admin_audit_log_target", table_name="admin_audit_log")
    op.drop_index(op.f("ix_admin_audit_log_created_at"), table_name="admin_audit_log")
    op.drop_table("admin_audit_log")
