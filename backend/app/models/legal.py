"""Documentos legales versionados y su aceptacion (docs/PLATAFORMA_COMPLETA.md §6.2).

Una version publicada no se edita: se publica una nueva. Asi cada fila de
`user_consents` apunta al texto exacto que el usuario tuvo delante.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_col, enum_col, uuid_pk

LEGAL_KINDS = ("terms", "privacy", "refunds", "cookies")


class LegalDocument(Base):
    __tablename__ = "legal_documents"
    __table_args__ = (UniqueConstraint("kind", "version", name="uq_legal_documents_kind_version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(
        enum_col(*LEGAL_KINDS, name="legal_document_kind", length=32), index=True, nullable=False
    )
    # Entero creciente por `kind`.
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    # Si publicar esta version obliga a quienes ya tienen cuenta a aceptarla.
    requires_acceptance: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Null = borrador: solo lo ve el admin y todavia se puede editar.
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Null en las versiones que sembro una migracion, o si el admin se elimino.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at_col()


class UserConsent(Base):
    __tablename__ = "user_consents"
    __table_args__ = (
        UniqueConstraint("user_id", "legal_document_id", name="uq_user_consents_user_document"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # RESTRICT: un documento con aceptaciones no se puede borrar.
    legal_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legal_documents.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # La IP real del cliente (uvicorn con --proxy-headers, §13.1). 45 = IPv6.
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(400))

    document: Mapped[LegalDocument] = relationship()
