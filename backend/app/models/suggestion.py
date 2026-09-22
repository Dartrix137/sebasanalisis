"""Recomendaciones del motor y sugerencias de banca.

Nomenclatura deliberada: `statistical_suggestions` y `recommendation`, nunca
`predictions`. Una fila dice que mercado recomendo el motor para el giro
siguiente a partir de la muestra ya ocurrida, con que fuerza de criterio y como
cerro. No afirma que ese resultado fuera a salir.

Desde la Fase 3 esta tabla **si se escribe**: una fila por recomendacion
emitida. Hasta el MVP estaba creada y vacia a proposito, y §3.3 del documento de
arquitectura pedia alinearla con el contrato de la API antes de guardar la
primera fila — por eso la migracion que agrega las columnas de recomendacion
renombra tambien `chi_square_pvalue` a `chi_square_pvalue_adjusted` (lo que se
expone es el p-valor ya corregido, §2.4) y agrega el intervalo de Wilson.
"""

import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, enum_col, uuid_pk

#: Que decidio el motor para el giro siguiente (§2.10).
DECISIONS = ("RECOMMEND", "NO_BET")

#: Banda de fuerza del `signal_score`. Describe el criterio interno sobre la
#: muestra ya ocurrida, no una probabilidad de acertar.
SIGNAL_BANDS = ("weak", "medium", "strong", "very_strong")

#: Como cerro la recomendacion contra el giro siguiente. Un `NO_BET` se queda en
#: PENDING para siempre: no hubo nada que acertar ni que fallar.
RECOMMENDATION_OUTCOMES = ("PENDING", "HIT", "MISS")


class StatisticalSuggestion(Base):
    __tablename__ = "statistical_suggestions"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    #: Ultimo giro registrado cuando se emitio la recomendacion. Null si la
    #: sesion todavia no tenia giros.
    spin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("spins.id", ondelete="SET NULL"), index=True
    )

    decision: Mapped[str] = mapped_column(
        enum_col(*DECISIONS, name="recommendation_decision"), nullable=False
    )
    #: Clave del mercado en el catalogo, ej. 'dozen:first+second'.
    market_key: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    option_label: Mapped[str] = mapped_column(String(80), nullable=False)

    #: 0-100. Fuerza del criterio interno, NO probabilidad de acertar (§2.10).
    signal_score: Mapped[float] = mapped_column(Float, nullable=False)
    signal_band: Mapped[str] = mapped_column(
        enum_col(*SIGNAL_BANDS, name="signal_band"), nullable=False
    )

    # Regla anti-falacia del jugador: la probabilidad teorica y la frecuencia
    # observada con shrinkage se guardan SIEMPRE juntas (§2). Desde la Fase 3
    # viajan en la respuesta de la API y en "¿Por que recomienda esto?", no en la
    # tarjeta principal.
    theoretical_probability: Mapped[float] = mapped_column(Float, nullable=False)
    observed_frequency_shrunk: Mapped[float] = mapped_column(Float, nullable=False)
    deviation: Mapped[float] = mapped_column(Float, nullable=False)
    #: Intervalo de Wilson sobre los conteos crudos de la ventana mas larga (§2.2).
    observed_ci_low: Mapped[float] = mapped_column(Float, nullable=False)
    observed_ci_high: Mapped[float] = mapped_column(Float, nullable=False)

    ev: Mapped[float] = mapped_column(Float, nullable=False)
    #: p-valor del chi-cuadrado YA corregido por Benjamini-Hochberg (§2.4). Null
    #: si la prueba no estaba activa para la categoria del mercado.
    chi_square_pvalue_adjusted: Mapped[float | None] = mapped_column(Float)

    #: Monto sugerido en centavos, nunca float (regla de dinero del proyecto).
    #: Null cuando la decision es NO_BET: no hay nada que apostar.
    stake_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="COP", nullable=False)

    outcome: Mapped[str] = mapped_column(
        enum_col(*RECOMMENDATION_OUTCOMES, name="recommendation_outcome"),
        default="PENDING",
        nullable=False,
    )
    #: Giro que resolvio la recomendacion. Null mientras siga PENDING.
    resolved_spin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("spins.id", ondelete="SET NULL"), index=True
    )

    window_size_used: Mapped[int] = mapped_column(Integer, nullable=False)
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
