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
def outbox() -> Iterator[list]:
    """Los correos que la API "envio" durante el test, en orden.

    Sustituye el sender real por un `FakeEmailSender`: ningun test envia correo.
    """
    from app.core.email import FakeEmailSender, get_email_sender
    from app.main import app

    fake = FakeEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: fake
    yield fake.sent
    app.dependency_overrides.pop(get_email_sender, None)


@pytest.fixture
def db(test_database: str) -> Iterator[object]:
    """Sesion directa a la base de test, para preparar o inspeccionar filas."""
    engine = create_engine(test_database, poolclass=None)
    with sessionmaker(bind=engine, future=True)() as session:
        yield session
    engine.dispose()


@pytest.fixture
def client(test_database: str, outbox: list) -> Iterator[TestClient]:
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
        register_with_consents(c, test_database)
        yield c
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def register_with_consents(client: TestClient, database_url: str) -> None:
    """Hace que `client.post("/auth/register", ...)` deje una cuenta lista para
    usar la mesa: con los documentos aceptados y con acceso.

    Desde la Fase 4 una cuenta nueva necesita dos cosas que casi ningun test
    trata: los consentimientos del registro (paso 2, §6.3) y que alguien le de
    acceso (paso 3, §2). Para no repetirlo en cada uno:

    - un registro que no menciona NINGUNO de los dos campos de consentimiento
      recibe los vigentes;
    - y la cuenta queda como `invited` sin vencimiento, directo en la base.

    Ojo: la respuesta del registro se arma antes de ese cambio, asi que sigue
    diciendo `access_type: "none"`.

    Un test que SI trata de consentimientos o de acceso registra con
    `client.request("POST", "/auth/register", ...)`, que no pasa por aqui, o
    con `register_raw`.
    """
    original = client.post

    def post(url, *args, json=None, **kwargs):
        if url != "/auth/register" or not isinstance(json, dict):
            return original(url, *args, json=json, **kwargs)
        if "accepted_document_ids" not in json and "adult_confirmed" not in json:
            json = {**json, **consent_fields(client)}
        response = original(url, *args, json=json, **kwargs)
        if response.status_code == 201:
            engine = create_engine(database_url)
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE users SET access_type='invited' WHERE id=:id"),
                    {"id": response.json()["user"]["id"]},
                )
            engine.dispose()
        return response

    client.post = post  # type: ignore[method-assign]


def register_raw(client: TestClient, email: str, password: str = "clave-segura-123") -> dict:
    """Registra como lo hace un cliente real: con los consentimientos y SIN
    acceso (`access_type = none`). Para los tests de acceso."""
    r = client.request(
        "POST",
        "/auth/register",
        json={"email": email, "password": password, **consent_fields(client)},
    )
    assert r.status_code == 201, r.text
    return r.json()


def consent_fields(client: TestClient) -> dict:
    """Los campos de consentimiento de un registro valido, con los documentos vigentes."""
    required = client.get("/legal/required").json()
    return {"accepted_document_ids": [d["id"] for d in required], "adult_confirmed": True}


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
    """Access token de un usuario normal con acceso a la mesa (`invited`)."""
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


# Lo que no es juego y por eso no exige `RequireAccess`. Lo usan los dos tests
# que recorren todas las rutas de juego (acceso y consentimiento).
OPEN_PREFIXES = (
    "/auth",
    "/legal",
    "/admin",
    # Planes y cotizacion: los usa justo quien todavia no tiene acceso.
    "/plans",
    "/billing",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
