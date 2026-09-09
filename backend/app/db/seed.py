"""Seed idempotente: usuario admin + ruleta europea y americana.

Se corre con `python -m app.db.seed`. Vuelve a correrlo cuantas veces quieras:
no duplica filas, actualiza la configuracion si ya existe.

La configuracion de cada variante se lee de `seed_data/*.json` y se valida contra
`GameVariantConfig` antes de tocar la base, para que un JSON mal formado falle
aqui y no silenciosamente dentro de `engine/probability.py`.
"""

import json
from pathlib import Path

from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Game, GameVariant, User
from app.schemas.auth import RegisterRequest
from app.schemas.games import GameVariantConfig

SEED_DATA = Path(__file__).parent / "seed_data"

# house_edge por variante: §2.1 y la tabla del documento de estrategia verificado.
ROULETTE_VARIANTS = [
    ("european", "Ruleta europea", 0.02703, "roulette_european.json"),
    ("american", "Ruleta americana", 0.05263, "roulette_american.json"),
]


def load_config(filename: str) -> GameVariantConfig:
    """Carga y valida un categories_json antes de persistirlo."""
    raw = json.loads((SEED_DATA / filename).read_text(encoding="utf-8"))
    return GameVariantConfig.model_validate(raw)


def seed_admin(db: Session) -> User:
    settings = get_settings()
    # Se valida con el mismo schema del registro: si el correo del .env no pasa
    # EmailStr, el admin sembrado jamas podria iniciar sesion. Falla aqui, no en
    # el primer intento de login.
    email = str(
        RegisterRequest(
            email=settings.seed_admin_email, password=settings.seed_admin_password
        ).email
    ).lower()
    user = db.scalar(select(User).where(User.email == email))
    if user:
        print(f"  admin ya existe: {email}")
        return user
    user = User(
        email=email,
        password_hash=PasswordHasher().hash(settings.seed_admin_password),
        display_name="Administrador",
        access_type="full",
        role="admin",
    )
    db.add(user)
    db.flush()
    print(f"  admin creado: {email}")
    return user


def seed_roulette(db: Session) -> Game:
    game = db.scalar(select(Game).where(Game.type == "roulette"))
    if not game:
        game = Game(name="Ruleta", type="roulette", active=True)
        db.add(game)
        db.flush()
        print("  juego creado: Ruleta")
    else:
        print("  juego ya existe: Ruleta")

    for variant_name, label, house_edge, filename in ROULETTE_VARIANTS:
        config = load_config(filename)
        variant = db.scalar(
            select(GameVariant).where(
                GameVariant.game_id == game.id, GameVariant.name == variant_name
            )
        )
        if variant:
            variant.categories_json = config.model_dump()
            variant.house_edge = house_edge
            variant.active = True
            action = "actualizada"
        else:
            db.add(
                GameVariant(
                    game_id=game.id,
                    name=variant_name,
                    house_edge=house_edge,
                    categories_json=config.model_dump(),
                    active=True,
                )
            )
            action = "creada"
        n_outcomes = len(config.possible_outcomes)
        n_cats = len(config.categories)
        print(f"  variante {action}: {label} ({n_outcomes} resultados, {n_cats} categorias)")
    return game


def main() -> None:
    print("Seed de Sebasanalisis")
    with SessionLocal() as db:
        seed_admin(db)
        seed_roulette(db)
        db.commit()
    print("Listo.")


if __name__ == "__main__":
    main()
