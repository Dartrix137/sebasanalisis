"""Sesiones de mesa: una partida acotada de un usuario sobre una variante."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, enum_col, uuid_pk

SESSION_STATUSES = ("active", "closed", "abandoned")


class GameSession(Base):
    __tablename__ = "game_sessions"
    __table_args__ = (
        CheckConstraint(
            "loss_limit IS NULL OR (loss_limit > 0 AND loss_limit <= bankroll_start)",
            name="ck_session_loss_limit_within_bankroll",
        ),
        # Los escalones son contadores de progresion: nunca negativos.
        CheckConstraint(
            "stage_martingale >= 0 AND stage_two_sector >= 0",
            name="ck_session_stages_not_negative",
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
    # Perdida neta (banca inicial - banca actual) en la que el usuario decidio
    # detenerse (§2.8). Opcional: sin el, las alertas usan umbrales por defecto.
    loss_limit: Mapped[float | None] = mapped_column(Numeric(14, 2))

    # Desde la Fase 3 la sesion no elige una progresion al crearse: la mesa
    # muestra las tres a la vez (plana, martingala, recuperacion de dos sectores)
    # y el usuario sigue la que quiera. Por eso cada una lleva su propio
    # contador en vez de haber un `strategy_selected` con un escalon unico.
    #
    # La plana no tiene contador porque no tiene progresion: siempre esta en el
    # escalon 0. Guardarlo seria una columna que solo puede valer 0.
    #
    # Cada escalon solo avanza cuando el usuario aposto con esa gestion
    # (`bets.strategy`), segun el cierre de la recomendacion
    # (`engine.bankroll.advance_stages_on_outcome`): es el de la serie que lleva
    # de verdad.
    stage_martingale: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stage_two_sector: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    spins: Mapped[list["Spin"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
