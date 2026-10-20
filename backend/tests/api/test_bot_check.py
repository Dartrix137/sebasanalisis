"""Registro, ingreso y olvido de contrasena con la verificacion contra bots encendida."""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.bot_check import get_bot_checker
from app.main import app
from tests.api.conftest import _register, consent_fields


class _Verificador:
    """Acepta solo el token `humano`, y anota con que accion se le pregunto."""

    site_key = "llave-del-sitio"

    def __init__(self) -> None:
        self.acciones: list[str] = []

    def verify(self, token: str | None, *, remote_ip: str | None, action: str) -> bool:
        self.acciones.append(action)
        return token == "humano"


@pytest.fixture
def verificador(client: TestClient) -> Iterator[_Verificador]:
    v = _Verificador()
    app.dependency_overrides[get_bot_checker] = lambda: v
    yield v


def _registro(client: TestClient, token: str | None) -> dict:
    cuerpo = {
        "email": f"bot-{uuid.uuid4().hex[:10]}@ejemplo.com",
        "password": "clave-segura-123",
        **consent_fields(client),
    }
    if token is not None:
        cuerpo["bot_check_token"] = token
    return cuerpo


def test_la_llave_del_sitio_es_publica(client: TestClient, verificador: _Verificador) -> None:
    assert client.get("/auth/bot-check").json() == {"site_key": "llave-del-sitio"}


def test_apagada_no_hay_llave(client: TestClient) -> None:
    assert client.get("/auth/bot-check").json() == {"site_key": None}


@pytest.mark.parametrize("token", [None, "robot"])
def test_el_registro_sin_un_token_valido_no_crea_la_cuenta(
    client: TestClient, verificador: _Verificador, token: str | None
) -> None:
    cuerpo = _registro(client, token)
    r = client.post("/auth/register", json=cuerpo)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "bot_check_failed"
    # La cuenta no existe: el ingreso con esos datos falla.
    login = client.post(
        "/auth/login",
        json={"email": cuerpo["email"], "password": cuerpo["password"], "bot_check_token": "humano"},
    )
    assert login.status_code == 401


def test_el_registro_con_un_token_valido_crea_la_cuenta(
    client: TestClient, verificador: _Verificador
) -> None:
    assert client.post("/auth/register", json=_registro(client, "humano")).status_code == 201
    assert verificador.acciones == ["register"]


def test_el_ingreso_pide_el_token_antes_de_mirar_la_contrasena(
    client: TestClient, verificador: _Verificador
) -> None:
    email = f"bot-{uuid.uuid4().hex[:10]}@ejemplo.com"
    app.dependency_overrides.pop(get_bot_checker)
    _register(client, email)
    app.dependency_overrides[get_bot_checker] = lambda: verificador

    sin_token = client.post("/auth/login", json={"email": email, "password": "clave-segura-123"})
    assert sin_token.status_code == 400
    con_token = client.post(
        "/auth/login",
        json={"email": email, "password": "clave-segura-123", "bot_check_token": "humano"},
    )
    assert con_token.status_code == 200
    assert verificador.acciones == ["login", "login"]


def test_el_olvido_de_contrasena_pide_el_token(
    client: TestClient, verificador: _Verificador, outbox: list
) -> None:
    email = f"bot-{uuid.uuid4().hex[:10]}@ejemplo.com"
    sin_token = client.post("/auth/forgot-password", json={"email": email})
    assert sin_token.status_code == 400
    con_token = client.post(
        "/auth/forgot-password", json={"email": email, "bot_check_token": "humano"}
    )
    assert con_token.status_code == 202
    assert verificador.acciones == ["forgot-password", "forgot-password"]
