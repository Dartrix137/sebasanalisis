"""Giros registrados en una sesion, en orden cronologico ascendente.

`spin_index` creciente = del mas antiguo al mas reciente. La carga inicial
invierte la lista antes de guardar si el usuario declara que la escribio con el
mas reciente primero (§3.5).
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_col, enum_col, uuid_pk

#: Como entro el numero. Ambos son ingreso manual del usuario: el proyecto no
#: lee pantallazos ni llama a ninguna IA (§3.5).
SPIN_SOURCES = (
    "manual",         # ingresado giro a giro durante la sesion
    "initial_batch",  # cargado de una vez al abrir la sesion
)


class Spin(Base):
    __tablename__ = "spins"
    __table_args__ = (UniqueConstraint("session_id", "spin_index", name="uq_spin_session_index"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    spin_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Texto, no entero: el modelo generico admite resultados como "00" (americana)
    # o etiquetas de otros juegos sin cambiar el schema.
    result_value: Mapped[str] = mapped_column(String(20), nullable=False)
    # length=20 y no el 13 de 'initial_batch': la migracion a1f4c07b93de ensancho
    # la columna a proposito para dejar holgura a valores futuros. El modelo lo
    # declara para no quedar en desacuerdo con la base por una diferencia que
    # nadie quiso.
    source: Mapped[str] = mapped_column(
        enum_col(*SPIN_SOURCES, name="spin_source", length=20),
        default="manual",
        nullable=False,
    )
    # Escalones de cada progresion ANTES de que este giro resolviera la
    # recomendacion pendiente. Deshacer el giro los restaura: `advance_stage` no
    # es invertible y recalcular replicando la partida pisaria un "reiniciar
    # progresion" hecho a mano.
    #
    # Son dos desde la Fase 3 porque la mesa lleva las tres progresiones a la vez
    # y cada una tiene su escalon (la plana no necesita columna: siempre es 0).
    stage_martingale_before: Mapped[int | None] = mapped_column(Integer)
    stage_two_sector_before: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at_col()

    session: Mapped["GameSession"] = relationship(back_populates="spins")
