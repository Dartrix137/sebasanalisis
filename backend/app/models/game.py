"""Juegos y sus variantes.

Toda la semantica del juego (resultados posibles, categorias, pagos) vive en
`GameVariant.categories_json`; el motor estadistico nunca la hardcodea.

Los metadatos del juego (slug, modulo, estado, icono, orden) son de la
plataforma multijuego (docs/PLATAFORMA_COMPLETA.md §7.2): deciden la URL, que
pantalla lo juega y como aparece en el menu. El motor no los lee.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_col, enum_col, uuid_pk

# Familia de juego: decide que pantalla y que motor se usan (§7.3). `sports` esta
# reservado para las apuestas deportivas (§8.2): existe en el enum, pero no tiene
# implementacion y el admin no deja crear un juego con el.
GAME_MODULES = ("discrete_outcome", "sports")

# `active`: en el menu y se juega. `hidden`: fuera del menu de los clientes; un
# administrador lo ve y lo prueba. `coming_soon`: en el menu, sin abrir mesas.
GAME_STATUSES = ("active", "hidden", "coming_soon")

# Iconos del menu: un set fijo que dibuja el frontend. No hay subida de archivos.
GAME_ICONS = ("ruleta", "dados", "cartas", "deportes", "generico")

# El slug va en la URL (`/juegos/<slug>`): minusculas, numeros y guiones.
SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class Game(Base):
    __tablename__ = "games"
    __table_args__ = (
        CheckConstraint(f"slug ~ '{SLUG_PATTERN}'", name="ck_games_slug_format"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Identificador interno estable ('roulette'). Lo usa el seed.
    type: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    # Va en la URL. No cambia despues de creado: romperia los enlaces guardados.
    slug: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    module: Mapped[str] = mapped_column(
        enum_col(*GAME_MODULES, name="game_module", length=32), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    icon: Mapped[str] = mapped_column(
        enum_col(*GAME_ICONS, name="game_icon", length=32), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    status: Mapped[str] = mapped_column(
        enum_col(*GAME_STATUSES, name="game_status", length=16), nullable=False
    )
    created_at: Mapped[datetime] = created_at_col()

    variants: Mapped[list["GameVariant"]] = relationship(
        back_populates="game",
        cascade="all, delete-orphan",
        order_by=lambda: (GameVariant.sort_order, GameVariant.name),
    )


class GameVariant(Base):
    __tablename__ = "game_variants"
    __table_args__ = (UniqueConstraint("game_id", "name", name="uq_game_variant_name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    house_edge: Mapped[float] = mapped_column(Numeric(6, 5), nullable=False)
    categories_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    game: Mapped[Game] = relationship(back_populates="variants")


class PlanGame(Base):
    """Un juego incluido en un plan (§7.4).

    Un plan sin filas incluye todos los juegos, tambien los que se creen
    despues. Lo lee `core/access.has_access` (regla n.º 7 de §2.2).
    """

    __tablename__ = "plan_games"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True
    )
    # RESTRICT: un juego que algun plan incluye no se borra por debajo. Los
    # juegos tampoco se borran desde el admin; se ocultan.
    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("games.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
