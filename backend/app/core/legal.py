"""Documentos legales vigentes y consentimientos (docs/PLATAFORMA_COMPLETA.md §6).

Dos reglas:

- El documento **vigente** de un tipo es su ultima version publicada. Es el que
  muestran las paginas publicas y el que se acepta.
- Un usuario esta al dia con un tipo si acepto una version igual o posterior a
  la ultima publicada con `requires_acceptance`. Asi una version nueva que no la
  exige (corregir una errata) no le pide nada a nadie, y una que si la exige se
  la pide a todos.

Aqui no se decide el acceso: eso es de `core/access.py`, que consulta este
modulo.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LegalDocument, User, UserConsent
from app.models.legal import LEGAL_KINDS

USER_AGENT_MAX_LENGTH = 400


class StaleDocumentError(Exception):
    """Se intento aceptar algo que no es la version vigente de su documento."""


@dataclass(frozen=True)
class PendingConsent:
    """Lo que al usuario le falta para estar al dia."""

    documents: list[LegalDocument]
    adult_confirmation_required: bool

    @property
    def any(self) -> bool:
        return bool(self.documents) or self.adult_confirmation_required


def current_documents(db: Session) -> list[LegalDocument]:
    """La ultima version publicada de cada tipo, en el orden de `LEGAL_KINDS`
    (terminos primero): es el orden en que se muestran y se aceptan."""
    latest = (
        select(LegalDocument.kind, func.max(LegalDocument.version).label("version"))
        .where(LegalDocument.published_at.is_not(None))
        .group_by(LegalDocument.kind)
        .subquery()
    )
    documents = db.scalars(
        select(LegalDocument).join(
            latest,
            (LegalDocument.kind == latest.c.kind) & (LegalDocument.version == latest.c.version),
        )
    )
    return sorted(documents, key=lambda doc: LEGAL_KINDS.index(doc.kind))


def current_document(db: Session, kind: str) -> LegalDocument | None:
    return db.scalar(
        select(LegalDocument)
        .where(LegalDocument.kind == kind, LegalDocument.published_at.is_not(None))
        .order_by(LegalDocument.version.desc())
        .limit(1)
    )


def _required_versions(db: Session) -> dict[str, int]:
    """Por tipo, la ultima version publicada que exige aceptacion."""
    rows = db.execute(
        select(LegalDocument.kind, func.max(LegalDocument.version))
        .where(
            LegalDocument.published_at.is_not(None),
            LegalDocument.requires_acceptance.is_(True),
        )
        .group_by(LegalDocument.kind)
    )
    return {kind: version for kind, version in rows}


def required_documents(db: Session) -> list[LegalDocument]:
    """Los documentos que hay que aceptar para tener cuenta: la version vigente
    de cada tipo que alguna vez exigio aceptacion."""
    required = _required_versions(db)
    return [doc for doc in current_documents(db) if doc.kind in required]


def pending_documents(db: Session, user: User) -> list[LegalDocument]:
    """Los documentos vigentes que este usuario todavia tiene que aceptar."""
    required = _required_versions(db)
    if not required:
        return []
    accepted = dict(
        db.execute(
            select(LegalDocument.kind, func.max(LegalDocument.version))
            .join(UserConsent, UserConsent.legal_document_id == LegalDocument.id)
            .where(UserConsent.user_id == user.id)
            .group_by(LegalDocument.kind)
        ).all()
    )
    return [
        doc
        for doc in current_documents(db)
        if doc.kind in required and accepted.get(doc.kind, 0) < required[doc.kind]
    ]


def pending_consent(db: Session, user: User) -> PendingConsent:
    return PendingConsent(
        documents=pending_documents(db, user),
        adult_confirmation_required=user.adult_confirmed_at is None,
    )


def record_consents(
    db: Session,
    user: User,
    document_ids: list,
    *,
    now: datetime,
    ip: str | None,
    user_agent: str | None,
) -> None:
    """Guarda una aceptacion por documento. No hace commit.

    Solo se puede aceptar la version vigente: si entre mostrar el documento y
    aceptarlo se publico otra, la aceptacion apuntaria a un texto que ya no es
    el que rige, y se rechaza para que el usuario lea el nuevo.
    """
    vigentes = {doc.id: doc for doc in current_documents(db)}
    ya_aceptados = set(
        db.scalars(select(UserConsent.legal_document_id).where(UserConsent.user_id == user.id))
    )
    for document_id in dict.fromkeys(document_ids):
        if document_id not in vigentes:
            raise StaleDocumentError
        if document_id in ya_aceptados:
            continue
        db.add(
            UserConsent(
                user_id=user.id,
                legal_document_id=document_id,
                accepted_at=now,
                ip=ip,
                user_agent=(user_agent or "")[:USER_AGENT_MAX_LENGTH] or None,
            )
        )
    db.flush()
