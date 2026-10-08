"""IP real del cliente detras del proxy, y su efecto en el rate limit de login.

En produccion uvicorn corre con `--proxy-headers --forwarded-allow-ips` (ver
`docker-entrypoint.sh`), que envuelve la app en `ProxyHeadersMiddleware`. Aqui
se envuelve con ese mismo middleware para probar lo que de verdad corre.
"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.rate_limit import MAX_ATTEMPTS
from tests.api.conftest import register_with_consents

PROXY_IP = "10.0.1.5"
PROXY_NETWORK = "10.0.1.0/24"
IP_A = "203.0.113.10"
IP_B = "198.51.100.20"


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@ejemplo.com"


@pytest.fixture
def proxied_client(test_database: str) -> Iterator[type[TestClient]]:
    """Fabrica de clientes cuya conexion llega desde la IP que se le indique."""
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
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts=PROXY_NETWORK)

    def make(peer_ip: str) -> TestClient:
        # TestClient siempre se presenta como "testclient": la IP de la conexion
        # se fija por fuera del middleware, que es donde la pondria el servidor.
        async def from_peer(scope, receive, send):  # type: ignore[no-untyped-def]
            if scope["type"] == "http":
                scope = {**scope, "client": (peer_ip, 50000)}
            await wrapped(scope, receive, send)

        client = TestClient(from_peer)
        register_with_consents(client)
        return client

    yield make  # type: ignore[misc]
    app.dependency_overrides.clear()
    engine.dispose()


def _login(client: TestClient, email: str, forwarded_for: str | None, password: str = "mala"):
    headers = {"X-Forwarded-For": forwarded_for} if forwarded_for else {}
    return client.post("/auth/login", json={"email": email, "password": password}, headers=headers)


def test_rate_limit_separa_dos_ip_detras_del_proxy(proxied_client) -> None:
    """Dos clientes distintos tras el mismo proxy no comparten el limite."""
    client = proxied_client(PROXY_IP)
    email = _email()
    client.post("/auth/register", json={"email": email, "password": "clave-segura-123"})

    for _ in range(MAX_ATTEMPTS):
        assert _login(client, email, IP_A).status_code == 401
    assert _login(client, email, IP_A).status_code == 429

    # Misma conexion del proxy, mismo correo, otra IP de cliente: no esta limitada.
    assert _login(client, email, IP_B).status_code == 401
    assert _login(client, email, IP_B, password="clave-segura-123").status_code == 200
    # Y la primera sigue bloqueada.
    assert _login(client, email, IP_A).status_code == 429


def test_x_forwarded_for_se_ignora_si_no_viene_del_proxy(proxied_client) -> None:
    """Quien llega directo no esquiva el limite inventandose la cabecera."""
    client = proxied_client("192.0.2.77")  # fuera de la red del proxy
    email = _email()
    client.post("/auth/register", json={"email": email, "password": "clave-segura-123"})

    for i in range(MAX_ATTEMPTS):
        assert _login(client, email, f"203.0.113.{i + 1}").status_code == 401
    assert _login(client, email, "203.0.113.99").status_code == 429


def test_cadena_de_proxies_toma_la_ip_que_agrego_el_proxy_de_confianza(proxied_client) -> None:
    """El cliente puede anteponer IPs falsas; cuenta la ultima, la que puso el proxy."""
    client = proxied_client(PROXY_IP)
    email = _email()
    client.post("/auth/register", json={"email": email, "password": "clave-segura-123"})

    for i in range(MAX_ATTEMPTS):
        assert _login(client, email, f"1.2.3.{i + 1}, {IP_A}").status_code == 401
    assert _login(client, email, f"9.9.9.9, {IP_A}").status_code == 429
