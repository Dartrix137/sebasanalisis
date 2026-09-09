"""Tests de integracion de auth contra PostgreSQL real."""

import uuid

import pytest
from fastapi.testclient import TestClient


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@ejemplo.com"


def test_register_login_me_flujo_completo(client: TestClient) -> None:
    """El flujo del paso 2: registro -> login -> /auth/me con un usuario real."""
    email, password = _email(), "clave-segura-123"

    r = client.post(
        "/auth/register",
        json={"email": email, "password": password, "display_name": "Sebastian"},
    )
    assert r.status_code == 201, r.text
    registered = r.json()
    assert registered["token_type"] == "bearer"
    assert registered["access_token"] and registered["refresh_token"]
    assert registered["user"]["email"] == email
    assert registered["user"]["display_name"] == "Sebastian"
    # El registro deja la cuenta activa de inmediato, sin verificacion de correo.
    assert registered["user"]["access_type"] == "trial"
    assert registered["user"]["role"] == "user"
    assert "password" not in r.text and "password_hash" not in r.text

    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    tokens = r.json()
    assert tokens["user"]["id"] == registered["user"]["id"]

    r = client.get("/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["id"] == registered["user"]["id"]
    assert me["email"] == email


def test_refresh_entrega_tokens_nuevos(client: TestClient) -> None:
    email, password = _email(), "clave-segura-123"
    client.post("/auth/register", json={"email": email, "password": password})
    login = client.post("/auth/login", json={"email": email, "password": password}).json()

    r = client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["email"] == email

    r = client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert r.status_code == 200


def test_correo_se_normaliza_a_minusculas(client: TestClient) -> None:
    email = _email()
    r = client.post("/auth/register", json={"email": email.upper(), "password": "clave-segura-123"})
    assert r.status_code == 201
    assert r.json()["user"]["email"] == email
    # Y el login funciona con cualquier capitalizacion.
    assert client.post(
        "/auth/login", json={"email": email.upper(), "password": "clave-segura-123"}
    ).status_code == 200


def test_correo_duplicado_es_rechazado(client: TestClient) -> None:
    email = _email()
    body = {"email": email, "password": "clave-segura-123"}
    assert client.post("/auth/register", json=body).status_code == 201
    assert client.post("/auth/register", json=body).status_code == 409


def test_contrasena_corta_es_rechazada(client: TestClient) -> None:
    r = client.post("/auth/register", json={"email": _email(), "password": "corta"})
    assert r.status_code == 422


@pytest.mark.parametrize("caso", ["correo_inexistente", "clave_incorrecta"])
def test_login_no_revela_si_el_correo_existe(client: TestClient, caso: str) -> None:
    """§3.6: el mensaje debe ser identico en ambos casos."""
    email = _email()
    client.post("/auth/register", json={"email": email, "password": "clave-segura-123"})

    if caso == "correo_inexistente":
        body = {"email": _email(), "password": "clave-segura-123"}
    else:
        body = {"email": email, "password": "clave-equivocada"}

    r = client.post("/auth/login", json=body)
    assert r.status_code == 401
    assert r.json()["detail"] == "Correo o contrasena incorrectos"


def test_me_rechaza_token_ausente_invalido_y_de_refresh(client: TestClient) -> None:
    email = _email()
    client.post("/auth/register", json={"email": email, "password": "clave-segura-123"})
    tokens = client.post(
        "/auth/login", json={"email": email, "password": "clave-segura-123"}
    ).json()

    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer basura"}).status_code == 401
    # Un refresh token no sirve para autenticar una peticion normal.
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"})
    assert r.status_code == 401


def test_refresh_rechaza_un_access_token(client: TestClient) -> None:
    email = _email()
    tokens = client.post(
        "/auth/register", json={"email": email, "password": "clave-segura-123"}
    ).json()
    r = client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert r.status_code == 401


def test_login_se_limita_tras_intentos_fallidos(client: TestClient) -> None:
    """§3.6: rate limiting por combinacion IP + correo."""
    email = _email()
    client.post("/auth/register", json={"email": email, "password": "clave-segura-123"})

    for _ in range(5):
        assert client.post(
            "/auth/login", json={"email": email, "password": "mala"}
        ).status_code == 401

    r = client.post("/auth/login", json={"email": email, "password": "mala"})
    assert r.status_code == 429
    # Incluso con la clave correcta sigue bloqueado dentro de la ventana.
    assert client.post(
        "/auth/login", json={"email": email, "password": "clave-segura-123"}
    ).status_code == 429
