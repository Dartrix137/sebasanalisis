"""Fixtures de tests de integracion.

Los tests corren contra una base PostgreSQL real (`sebasanalisis_test`, creada
al vuelo en el mismo contenedor), no contra SQLite: el schema usa JSONB, UUID
nativo y CHECK constraints que SQLite no reproduce.
"""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

TEST_DB_NAME = "sebasanalisis_test"


@pytest.fixture(scope="session", autouse=True)
def test_database() -> Iterator[str]:
    """Crea la base de test desde cero y aplica el schema con Alembic."""
    base_url = get_settings().database_url
    admin_url = base_url.rsplit("/", 1)[0] + "/postgres"
    test_url = base_url.rsplit("/", 1)[0] + f"/{TEST_DB_NAME}"

    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{TEST_DB_NAME}' AND pid <> pg_backend_pid()"
            )
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin.dispose()

    os.environ["DATABASE_URL"] = test_url
    get_settings.cache_clear()

    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", test_url)
    command.upgrade(cfg, "head")

    yield test_url

    get_settings.cache_clear()


@pytest.fixture
def client(test_database: str) -> Iterator[TestClient]:
    """Cliente HTTP con la sesion de DB apuntando a la base de test."""
    from app.db.session import get_db
    from app.main import app

    engine = create_engine(test_database, poolclass=None)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

    def override_get_db() -> Iterator[object]:
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_rate_limit() -> Iterator[None]:
    """El limitador vive en memoria del proceso: se limpia entre tests."""
    from app.core import rate_limit

    rate_limit.reset_all()
    yield
    rate_limit.reset_all()


def _register(client, email: str, password: str = "clave-segura-123") -> dict:
    return client.post("/auth/register", json={"email": email, "password": password}).json()


@pytest.fixture
def user_token(client) -> str:
    """Access token de un usuario normal (access_type='trial', role='user')."""
    import uuid

    return _register(client, f"user-{uuid.uuid4().hex[:12]}@ejemplo.com")["access_token"]


@pytest.fixture
def admin_token(client, test_database: str) -> str:
    """Access token de un usuario promovido a admin directamente en la base."""
    import uuid

    email = f"admin-{uuid.uuid4().hex[:12]}@ejemplo.com"
    _register(client, email)
    engine = create_engine(test_database)
    with engine.begin() as conn:
        conn.execute(text("UPDATE users SET role='admin' WHERE email=:e"), {"e": email})
    engine.dispose()
    return client.post(
        "/auth/login", json={"email": email, "password": "clave-segura-123"}
    ).json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
