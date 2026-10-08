"""Admin: versiones de los documentos legales (docs/PLATAFORMA_COMPLETA.md §6.2).

El texto se edita como Markdown mientras es borrador. Publicar lo congela: una
version publicada no se edita, se publica otra. Asi cada aceptacion apunta al
texto exacto que el usuario vio.

Publicar deja fila en `admin_audit_log` (§4.6), en la misma transaccion.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from app.api.deps import AdminUser, DbSession
from app.core import audit
from app.models import LegalDocument
from app.schemas.legal import (
    AdminLegalDocumentResponse,
    CreateLegalDocumentRequest,
    LegalKind,
    UpdateLegalDocumentRequest,
)

router = APIRouter(prefix="/admin/legal-documents", tags=["admin"])

_PUBLISHED = "Esta versión ya está publicada y no se puede editar. Crea una versión nueva"


def _get_or_404(db: DbSession, document_id: UUID) -> LegalDocument:
    document = db.get(LegalDocument, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Documento no encontrado"
        )
    return document


@router.get("", response_model=list[AdminLegalDocumentResponse])
def list_documents(
    db: DbSession, admin: AdminUser, kind: LegalKind | None = None
) -> list[LegalDocument]:
    """Todas las versiones, borradores incluidos; la mas reciente de cada tipo primero."""
    query = select(LegalDocument).order_by(LegalDocument.kind, LegalDocument.version.desc())
    if kind is not None:
        query = query.where(LegalDocument.kind == kind.value)
    return list(db.scalars(query))


@router.post("", response_model=AdminLegalDocumentResponse, status_code=status.HTTP_201_CREATED)
def create_document(
    payload: CreateLegalDocumentRequest, db: DbSession, admin: AdminUser
) -> LegalDocument:
    """Crea el borrador de la version siguiente de un documento."""
    # Un solo borrador por tipo: con dos, el numero de version de cada uno
    # dependeria de cual se publique primero.
    if db.scalar(
        select(LegalDocument.id).where(
            LegalDocument.kind == payload.kind.value, LegalDocument.published_at.is_(None)
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya hay un borrador de ese documento. Edítalo o publícalo",
        )
    last = db.scalar(
        select(func.max(LegalDocument.version)).where(LegalDocument.kind == payload.kind.value)
    )
    document = LegalDocument(
        kind=payload.kind.value,
        version=(last or 0) + 1,
        title=payload.title.strip(),
        content_md=payload.content_md,
        requires_acceptance=payload.requires_acceptance,
        created_by=admin.id,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


@router.patch("/{document_id}", response_model=AdminLegalDocumentResponse)
def update_document(
    document_id: UUID, payload: UpdateLegalDocumentRequest, db: DbSession, admin: AdminUser
) -> LegalDocument:
    document = _get_or_404(db, document_id)
    if document.published_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_PUBLISHED)
    document.title = payload.title.strip()
    document.content_md = payload.content_md
    document.requires_acceptance = payload.requires_acceptance
    db.commit()
    db.refresh(document)
    return document


@router.post("/{document_id}/publish", response_model=AdminLegalDocumentResponse)
def publish_document(
    document_id: UUID, db: DbSession, admin: AdminUser, request: Request
) -> LegalDocument:
    """Publica el borrador. Desde aqui es la version vigente y no se edita.

    Si exige aceptacion, toda cuenta que no la haya aceptado deja de tener
    acceso a la mesa hasta que lo haga (`core/access.has_access`).
    """
    document = _get_or_404(db, document_id)
    if document.published_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Esta versión ya está publicada"
        )
    document.published_at = datetime.now(UTC)
    audit.record(
        db,
        admin,
        action="legal_document.publish",
        target_type="legal_document",
        target_id=document.id,
        after={
            "kind": document.kind,
            "version": document.version,
            "requires_acceptance": document.requires_acceptance,
        },
        ip=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(document)
    return document
