"""quita el pipeline de pantallazos: carga inicial manual en su lugar

Se descarto integrar un modelo de vision para leer los numeros de un pantallazo
(§3.5). Los numeros los ingresa siempre el usuario: giro a giro (`manual`) o de
una vez al abrir la sesion (`initial_batch`).

Revision ID: a1f4c07b93de
Revises: 6d1cb2c2210c
Create Date: 2026-09-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1f4c07b93de"
down_revision: Union[str, None] = "6d1cb2c2210c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Cortar la referencia de spins a la tabla de pantallazos.
    op.drop_constraint("spins_screenshot_upload_id_fkey", "spins", type_="foreignkey")
    op.drop_column("spins", "screenshot_upload_id")

    # 2. La tabla de pantallazos completa.
    op.drop_index("ix_screenshot_uploads_user_id", table_name="screenshot_uploads")
    op.drop_index("ix_screenshot_uploads_session_id", table_name="screenshot_uploads")
    op.drop_index("ix_screenshot_uploads_image_hash", table_name="screenshot_uploads")
    op.drop_table("screenshot_uploads")

    # 3. `source` cambia de valores. El CHECK se recrea, no se altera: el enum se
    #    materializa como VARCHAR + CHECK (ver `enum_col` en models/base.py).
    op.drop_constraint("spin_source", "spins", type_="check")

    # 'initial_batch' son 13 caracteres y la columna era VARCHAR(10), dimensionada
    # para 'screenshot'. Sin ensanchar, toda carga inicial fallaria al insertar.
    op.alter_column(
        "spins",
        "source",
        existing_type=sa.String(length=10),
        type_=sa.String(length=20),
        existing_nullable=False,
    )

    # Cualquier giro que hubiera quedado marcado como extraido de un pantallazo
    # pasa a 'manual': lo ingreso una persona igual, y el CHECK nuevo lo rechazaria.
    op.execute("UPDATE spins SET source = 'manual' WHERE source = 'screenshot'")

    op.create_check_constraint(
        "spin_source", "spins", "source IN ('manual', 'initial_batch')"
    )


def downgrade() -> None:
    op.drop_constraint("spin_source", "spins", type_="check")
    op.execute("UPDATE spins SET source = 'manual' WHERE source = 'initial_batch'")
    op.alter_column(
        "spins",
        "source",
        existing_type=sa.String(length=20),
        type_=sa.String(length=10),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "spin_source", "spins", "source IN ('manual', 'screenshot')"
    )

    op.create_table(
        "screenshot_uploads",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("image_hash", sa.String(length=128), nullable=False),
        sa.Column("storage_url", sa.Text(), nullable=True),
        sa.Column(
            "classification_result_json",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "extraction_result_json",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "rejected_not_relevant",
                "needs_confirmation",
                "ready_for_extraction",
                "confirmed",
                "discarded_by_user",
                "failed",
                name="screenshot_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["session_id"], ["game_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_screenshot_uploads_image_hash", "screenshot_uploads", ["image_hash"])
    op.create_index("ix_screenshot_uploads_session_id", "screenshot_uploads", ["session_id"])
    op.create_index("ix_screenshot_uploads_user_id", "screenshot_uploads", ["user_id"])

    op.add_column("spins", sa.Column("screenshot_upload_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "spins_screenshot_upload_id_fkey",
        "spins",
        "screenshot_uploads",
        ["screenshot_upload_id"],
        ["id"],
        ondelete="SET NULL",
    )
