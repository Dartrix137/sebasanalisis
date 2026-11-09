"""legal_documents: version 2 de terminos, datos y cookies (borradores)

Fase 5, paso 5.5 (docs/PLATAFORMA_COMPLETA.md §6). Migracion de datos,
separada del DDL.

Inserta la version 2 de los tres documentos que quedan, como **borradores**
(sin publicar): se publican desde /admin/legal el dia en que entran en vigencia.
Publicar los terminos y la politica de datos le pide a todas las cuentas
aceptarlos de nuevo, y el job de renovaciones les avisa por correo (§6.7).

- `terms`: los Terminos y Condiciones del abogado, transcritos tal cual del PDF
  (`docs/reference/terminos-y-condiciones-abogado-v01.pdf`). Incluyen la
  cancelacion y los reembolsos: la politica de reembolsos se retira
  (`RETIRED_LEGAL_KINDS`) y no tiene version 2.
- `privacy` y `cookies`: escritas el 2026-11-09 a partir de lo que la plataforma
  guarda y usa hoy.

Si un borrador del mismo tipo ya existe (lo creo un administrador), no se
inserta el de la migracion para ese tipo: no puede haber dos borradores por
tipo, y el del administrador puede tener cambios.

El contenido se lee de `migrations/data/legal_v2/`, que queda congelado junto
con esta migracion: no se edita. Un cambio de texto se hace en el borrador desde
el admin, o en una version nueva.

Revision ID: 7b636895d186
Revises: fbce7237bed1
Create Date: 2026-11-09
"""

import uuid
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "7b636895d186"
down_revision: str | None = "fbce7237bed1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "legal_v2"

# (kind, titulo, exige aceptacion)
DOCUMENTS = [
    ("terms", "Términos y Condiciones", True),
    ("privacy", "Política de Tratamiento de Datos Personales", True),
    ("cookies", "Política de Cookies", False),
]

#: Marca las filas de esta migracion, para que el downgrade borre solo esas.
_SEED_NOTE = "migracion 7b636895d186"


def upgrade() -> None:
    conn = op.get_bind()
    for kind, title, requires_acceptance in DOCUMENTS:
        draft = conn.execute(
            sa.text("SELECT 1 FROM legal_documents WHERE kind = :k AND published_at IS NULL"),
            {"k": kind},
        ).first()
        if draft:
            continue
        last = conn.execute(
            sa.text("SELECT COALESCE(MAX(version), 0) FROM legal_documents WHERE kind = :k"),
            {"k": kind},
        ).scalar_one()
        conn.execute(
            sa.text(
                "INSERT INTO legal_documents "
                "(id, kind, version, title, content_md, requires_acceptance, published_at, "
                "created_at) "
                "VALUES (:id, :kind, :version, :title, :content, :req, NULL, now())"
            ),
            {
                "id": uuid.uuid5(uuid.NAMESPACE_URL, f"{_SEED_NOTE}/{kind}"),
                "kind": kind,
                "version": last + 1,
                "title": title,
                "content": (DATA_DIR / f"{kind}.md").read_text(encoding="utf-8"),
                "req": requires_acceptance,
            },
        )


def downgrade() -> None:
    # Solo las filas de esta migracion (su id es fijo), y solo si siguen siendo
    # borradores: una version publicada ya puede tener aceptaciones y avisos, y
    # borrarla haria perder la constancia de lo que se acepto.
    ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"{_SEED_NOTE}/{kind}")) for kind, _, _ in DOCUMENTS]
    op.get_bind().execute(
        sa.text(
            "DELETE FROM legal_documents WHERE published_at IS NULL "
            "AND id::text = ANY(:ids)"
        ),
        {"ids": ids},
    )
