"""Documentos legales: lectura publica y aceptacion (docs/PLATAFORMA_COMPLETA.md §6).

Este router NO exige `RequireAccess`: quien tiene documentos por aceptar tiene
que poder leerlos y aceptarlos, que es justo lo que le falta para tener acceso.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core import legal
from app.models import LegalDocument, UserConsent
from app.schemas.legal import (
    AcceptLegalRequest,
    ConsentResponse,
    LegalDocumentResponse,
    LegalKind,
    PendingConsentResponse,
)

router = APIRouter(prefix="/legal", tags=["legal"])

STALE_DOCUMENT_MESSAGE = (
    "Se publicó una versión nueva de un documento. Recarga la página para leerla"
)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/required", response_model=list[LegalDocumentResponse])
def required_documents(db: DbSession) -> list[LegalDocument]:
    """Los documentos que hay que aceptar para crear una cuenta. Publico."""
    return legal.required_documents(db)


@router.get("/pending", response_model=PendingConsentResponse)
def pending(user: CurrentUser, db: DbSession) -> legal.PendingConsent:
    """Lo que esta cuenta debe aceptar antes de usar la mesa."""
    return legal.pending_consent(db, user)


@router.post("/accept", response_model=PendingConsentResponse)
def accept(
    payload: AcceptLegalRequest, user: CurrentUser, db: DbSession, request: Request
) -> legal.PendingConsent:
    """Registra la aceptacion y devuelve lo que todavia queda pendiente."""
    now = datetime.now(UTC)
    try:
        legal.record_consents(
            db,
            user,
            payload.legal_document_ids,
            now=now,
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except legal.StaleDocumentError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=STALE_DOCUMENT_MESSAGE
        ) from None
    if payload.adult_confirmed and user.adult_confirmed_at is None:
        user.adult_confirmed_at = now
    db.commit()
    db.refresh(user)
    return legal.pending_consent(db, user)


@router.get("/consents", response_model=list[ConsentResponse])
def consents(user: CurrentUser, db: DbSession) -> list[ConsentResponse]:
    """Los documentos que la cuenta acepto, del mas reciente al mas antiguo."""
    return list_consents(db, user.id)


def list_consents(db: DbSession, user_id: object) -> list[ConsentResponse]:
    vigentes = {doc.id for doc in legal.current_documents(db)}
    rows = db.execute(
        select(UserConsent, LegalDocument)
        .join(LegalDocument, UserConsent.legal_document_id == LegalDocument.id)
        .where(UserConsent.user_id == user_id)
        .order_by(UserConsent.accepted_at.desc(), LegalDocument.kind)
    )
    return [
        ConsentResponse(
            legal_document_id=doc.id,
            kind=LegalKind(doc.kind),
            title=doc.title,
            version=doc.version,
            accepted_at=consent.accepted_at,
            current=doc.id in vigentes,
        )
        for consent, doc in rows
    ]


# Va al final: `/{kind}` no debe capturar las rutas fijas de arriba.
@router.get("/{kind}", response_model=LegalDocumentResponse)
def current_document(kind: LegalKind, db: DbSession) -> LegalDocument:
    """La ultima version publicada de un documento. Publico."""
    document = legal.current_document(db, kind.value)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ese documento todavía no está publicado"
        )
    return document
