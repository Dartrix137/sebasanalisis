"""
Schemas: documentos legales y consentimientos (§6 de la Fase 4)
"""
from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.base import ApiModel


class LegalKind(str, Enum):
    terms = "terms"
    privacy = "privacy"
    refunds = "refunds"
    cookies = "cookies"


# ---------- Publico y usuario ----------

class LegalDocumentResponse(ApiModel):
    """Una version publicada, con su texto en Markdown."""
    id: UUID
    kind: LegalKind
    version: int
    title: str
    content_md: str
    requires_acceptance: bool
    published_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PendingConsentResponse(ApiModel):
    """Lo que la cuenta debe aceptar antes de usar la mesa."""
    documents: list[LegalDocumentResponse]
    adult_confirmation_required: bool


class AcceptLegalRequest(ApiModel):
    legal_document_ids: list[UUID] = Field(default_factory=list, max_length=20)
    # La declaracion de mayoria de edad, para las cuentas que no la hicieron al
    # registrarse.
    adult_confirmed: bool = False


class ConsentResponse(ApiModel):
    """Un documento que el usuario acepto, para la pagina de cuenta."""
    legal_document_id: UUID
    kind: LegalKind
    title: str
    version: int
    accepted_at: datetime
    # Si la version aceptada es la que rige hoy.
    current: bool


# ---------- Admin ----------

class AdminLegalDocumentResponse(ApiModel):
    """Cualquier version, publicada o borrador."""
    id: UUID
    kind: LegalKind
    version: int
    title: str
    content_md: str
    requires_acceptance: bool
    published_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CreateLegalDocumentRequest(ApiModel):
    kind: LegalKind
    title: str = Field(min_length=1, max_length=200)
    content_md: str = Field(min_length=1, max_length=200_000)
    requires_acceptance: bool


class UpdateLegalDocumentRequest(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    content_md: str = Field(min_length=1, max_length=200_000)
    requires_acceptance: bool
