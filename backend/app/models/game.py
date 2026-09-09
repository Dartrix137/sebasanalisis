"""Juegos y sus variantes.

Toda la semantica del juego (resultados posibles, categorias, pagos) vive en
`GameVariant.categories_json`; el motor estadistico nunca la hardcodea.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_col, uuid_pk


class Game(Base):
    __tablename__ = "games"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = created_at_col()

    variants: Mapped[list["GameVariant"]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )


class GameVariant(Base):
    __tablename__ = "game_variants"
    __table_args__ = (UniqueConstraint("game_id", "name", name="uq_game_variant_name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    house_edge: Mapped[float] = mapped_column(Numeric(6, 5), nullable=False)
    categories_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    game: Mapped[Game] = relationship(back_populates="variants")
