"""Sesiones de mesa: una partida acotada de un usuario sobre una variante."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, enum_col, uuid_pk

SESSION_STATUSES = ("active", "closed", "abandoned")
STRATEGY_MODES = ("single", "two_sector")
STRATEGIES = ("flat", "martingale", "dalembert", "fibonacci", "two_sector_recovery")


class GameSession(Base):
    __tablename__ = "game_sessions"
    __table_args__ = (
        # Regla cruzada de `docs/ARQUITECTURA_Y_ESTADISTICA.md` §2.8, replicada en DB:
        # el modo dos-sectores exige la progresion de recuperacion, y esa progresion
        # no aplica en modo 1:1. El schema Pydantic la valida primero; esto es la red.
        CheckConstraint(
            "(strategy_mode = 'two_sector') = (strategy_selected = 'two_sector_recovery')",
            name="ck_session_strategy_mode_matches_strategy",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    game_variant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game_variants.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        enum_col(*SESSION_STATUSES, name="session_status"), default="active", nullable=False
    )
    # Limite superior de giros cargados para el calculo (rendimiento). El peso real
    # de cada observacion es exponencial por recencia, no binario (§2.3).
    window_size: Mapped[int] = mapped_column(Integer, default=50, nullable=False)

    # NOT NULL: `CreateSessionRequest` los exige todos (gt=0) y `SessionResponse`
    # los devuelve como requeridos, asi que una fila con NULL solo podria venir de
    # una escritura fuera de la API y reventaria al serializar.
    bankroll_start: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    bankroll_current: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    base_bet: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    table_limit: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)

    strategy_selected: Mapped[str] = mapped_column(
        enum_col(*STRATEGIES, name="strategy_selected"), default="flat", nullable=False
    )
    strategy_stage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    strategy_mode: Mapped[str] = mapped_column(
        enum_col(*STRATEGY_MODES, name="strategy_mode"), default="single", nullable=False
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    spins: Mapped[list["Spin"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
