"""legal_documents: version 1 de los cuatro documentos (borradores publicados)

Fase 4, paso 2 (docs/PLATAFORMA_COMPLETA.md §6). Migracion de datos, separada
del DDL.

Inserta la version 1 de terminos, privacidad, reembolsos y cookies, ya
publicada: el registro exige aceptar los terminos y la politica de datos, asi
que sin una version publicada nadie podria crear una cuenta tras desplegar.

Los textos son BORRADORES sin revisar por un abogado y lo dicen en su primer
parrafo. El texto revisado se publica despues desde /admin/legal como version
2, y eso le pide a todas las cuentas aceptarlo de nuevo.

El contenido se lee de `migrations/data/legal_v1/`, que queda congelado junto
con esta migracion: no se edita. Un cambio de texto es una version nueva.

Revision ID: c3f81a5d7e20
Revises: b72c4e9d1a63
Create Date: 2026-10-08
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "c3f81a5d7e20"
down_revision: str | None = "b72c4e9d1a63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "legal_v1"

# (kind, titulo, exige aceptacion)
DOCUMENTS = [
    ("terms", "Términos y Condiciones", True),
    ("privacy", "Política de Tratamiento de Datos Personales", True),
    ("refunds", "Política de Cancelación y Reembolsos", False),
    ("cookies", "Política de Cookies y Almacenamiento Local", False),
]

legal_documents = sa.table(
    "legal_documents",
    sa.column("id", sa.UUID()),
    sa.column("kind", sa.String()),
    sa.column("version", sa.Integer()),
    sa.column("title", sa.String()),
    sa.column("content_md", sa.Text()),
    sa.column("requires_acceptance", sa.Boolean()),
    sa.column("published_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    published_at = datetime.now(UTC)
    op.bulk_insert(
        legal_documents,
        [
            {
                "id": uuid.uuid4(),
                "kind": kind,
                "version": 1,
                "title": title,
                "content_md": (DATA_DIR / f"{kind}.md").read_text(encoding="utf-8"),
                "requires_acceptance": requires_acceptance,
                "published_at": published_at,
            }
            for kind, title, requires_acceptance in DOCUMENTS
        ],
    )


def downgrade() -> None:
    # Las aceptaciones de la version 1 se van con ella: sin el documento no
    # dicen que se acepto (y la FK no deja borrarlo mientras existan).
    op.execute(
        "DELETE FROM user_consents WHERE legal_document_id IN "
        "(SELECT id FROM legal_documents WHERE version = 1)"
    )
    op.execute("DELETE FROM legal_documents WHERE version = 1")
