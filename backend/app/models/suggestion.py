"""Sugerencias estadisticas y sugerencias de banca.

Nomenclatura deliberada: `statistical_suggestions`, nunca `predictions`. Estas
filas describen desviaciones observadas en la muestra ya ocurrida; no anticipan
el resultado de un giro futuro (ver §0 del documento de arquitectura).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, enum_col, uuid_pk

SIGNAL_STRENGTHS = ("strong", "medium", "weak")


class StatisticalSuggestion(Base):
    __tablename__ = "statistical_suggestions"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    spin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("spins.id", ondelete="SET NULL"), index=True
    )
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    option_label: Mapped[str] = mapped_column(String(60), nullable=False)

    # Regla anti-falacia del jugador: la probabilidad teorica y la frecuencia
    # observada con shrinkage se guardan y se muestran SIEMPRE juntas (§2).
    theoretical_probability: Mapped[float] = mapped_column(Float, nullable=False)
    observed_frequency_shrunk: Mapped[float] = mapped_column(Float, nullable=False)
    deviation: Mapped[float] = mapped_column(Float, nullable=False)

    significance_score: Mapped[float] = mapped_column(Float, nullable=False)
    strength: Mapped[str] = mapped_column(
        enum_col(*SIGNAL_STRENGTHS, name="signal_strength"), nullable=False
    )
    ev: Mapped[float] = mapped_column(Float, nullable=False)
    chi_square_pvalue: Mapped[float | None] = mapped_column(Float)

    window_size_used: Mapped[int] = mapped_column(Integer, nullable=False)
    is_top3: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class BankrollSuggestion(Base):
    __tablename__ = "bankroll_suggestions"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    spin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("spins.id", ondelete="SET NULL"), index=True
    )
    strategy: Mapped[str] = mapped_column(String(40), nullable=False)
    suggested_bet: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    stage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    risk_warning: Mapped[str | None] = mapped_column(Text)
    ruin_probability_estimate: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = created_at_col()
