"""Apuestas reales registradas por el usuario y su resolucion."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, enum_col, uuid_pk

BET_STATUSES = ("pending", "resolved", "cancelled")


class Bet(Base):
    __tablename__ = "bets"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    spin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("spins.id", ondelete="SET NULL"), index=True
    )
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    option_label: Mapped[str] = mapped_column(String(60), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    # Si el usuario siguio o no la sugerencia estadistica mostrada. Alimenta la
    # auto-evaluacion (§2.7); no implica que la sugerencia anticipara el resultado.
    followed_suggestion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(
        enum_col(*BET_STATUSES, name="bet_status"), default="pending", nullable=False
    )
    won: Mapped[bool | None] = mapped_column(Boolean)
    payout: Mapped[float | None] = mapped_column(Numeric(14, 2))
    net_change: Mapped[float | None] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = created_at_col()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
