"""Deja lista la base de los tests de punta a punta (Playwright).

Borra y vuelve a crear la base que indique DATABASE_URL, aplica las migraciones
y corre el seed (administrador y variantes de ruleta). Se niega a tocar una base
cuyo nombre no termine en `_e2e`: este script BORRA la base que recibe.

    DATABASE_URL=postgresql+psycopg://.../sebasanalisis_e2e python scripts/prepare_e2e_db.py
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import get_settings  # noqa: E402


def main() -> None:
    url = get_settings().database_url
    base, name = url.rsplit("/", 1)
    if not name.endswith("_e2e"):
        sys.exit(f"Me niego a recrear '{name}': el nombre de la base debe terminar en _e2e.")

    admin = create_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": name},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()

    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")

    from app.db.seed import main as seed

    seed()
    print(f"Base de punta a punta lista: {name}")


if __name__ == "__main__":
    main()
