"""Auto-evaluacion del motor contra una linea base ingenua (§2.7).

Requisito de producto del MVP: si el motor no supera la linea base, la UI debe
decirlo explicitamente. `matched_suggestions` cuenta coincidencias con el
resultado observado, no "aciertos" de una prediccion.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class SessionPerformance(Base):
    __tablename__ = "session_performance"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    total_suggestions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    matched_suggestions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    baseline_matched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
