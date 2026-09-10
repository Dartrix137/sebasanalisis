"""Base declarativa y mixins compartidos por todos los modelos."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from sqlalchemy.dialects.postgresql import UUID as PGUUID


class Base(DeclarativeBase):
    """Base declarativa unica: Alembic autogenera contra su metadata."""


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_at_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def enum_col(*values: str, name: str, length: int | None = None):
    """Enum portable: se materializa como VARCHAR + CHECK, no como tipo nativo de PG.

    Evita el dolor de ALTER TYPE en migraciones futuras cuando se agreguen juegos
    o estados nuevos desde el admin.

    `length` fija el ancho del VARCHAR. Sin el, SQLAlchemy lo deriva del valor
    mas largo, y entonces cualquier columna que una migracion haya ensanchado a
    proposito queda distinta a su modelo: `alembic check` reporta un cambio
    pendiente eterno y deja de servir para detectar drift de verdad.
    """
    # create_constraint=True es explicito a proposito: desde SQLAlchemy 1.4 el
    # default es False, y sin el la columna queda como VARCHAR libre sin CHECK.
    return SAEnum(
        *values,
        name=name,
        native_enum=False,
        validate_strings=True,
        create_constraint=True,
        length=length,
    )
