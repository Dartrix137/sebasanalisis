"""Revision de seguridad del paso 9 (Fase 4), convertida en tests.

Recorren TODAS las rutas del OpenAPI, asi que una ruta nueva queda cubierta
sin escribir nada: si es publica, va en `PUBLICAS`; si no, tiene que pedir
sesion, no mostrarle a una cuenta lo de otra, y no dejar entrar al admin a
quien no lo es. El aislamiento entre cuentas lo hace el codigo (no hay
Row-Level Security en Postgres, decidido el 2026-10-20): estos tests son su
garantia.
"""

import re
import uuid

from fastapi.testclient import TestClient

from app.main import app
from tests.api.conftest import _register, auth, consent_fields
from tests.api.test_spins import _crear_sesion, variant_id  # noqa: F401

# Lo unico que responde sin sesion. Todo lo demas, 401.
PUBLICAS = {
    ("GET", "/health"),
    ("GET", "/legal/required"),
    ("GET", "/legal/{kind}"),
    ("GET", "/plans"),
    ("GET", "/billing/availability"),
    ("GET", "/auth/bot-check"),
    ("POST", "/auth/register"),
    ("POST", "/auth/login"),
    ("POST", "/auth/refresh"),
    ("POST", "/auth/verify-email"),
    ("POST", "/auth/forgot-password"),
    ("POST", "/auth/reset-password"),
}


def _rutas() -> list[tuple[str, str]]:
    return [
        (metodo.upper(), ruta)
        for ruta, operaciones in app.openapi()["paths"].items()
        for metodo in operaciones
    ]


def _url(ruta: str, valores: dict[str, str]) -> str:
    def poner(m: re.Match[str]) -> str:
        nombre = m.group(1)
        if nombre in valores:
            return valores[nombre]
        if "slug" in nombre:
            return "ruleta"
        if nombre == "kind":
            return "terms"
        return str(uuid.uuid4())

    return re.sub(r"\{([^}:]+)(?::[^}]*)?\}", poner, ruta)


def _cuerpo(metodo: str) -> dict | None:
    return {} if metodo in {"POST", "PUT", "PATCH"} else None


def test_ninguna_ruta_privada_responde_sin_sesion(client: TestClient) -> None:
    rutas = _rutas()
    assert PUBLICAS <= set(rutas), "una ruta publica de la lista ya no existe"
    abiertas = []
    for metodo, ruta in rutas:
        if (metodo, ruta) in PUBLICAS:
            continue
        r = client.request(metodo, _url(ruta, {}), json=_cuerpo(metodo))
        if r.status_code != 401:
            abiertas.append(f"{metodo} {ruta} -> {r.status_code}")
    assert abiertas == []


def test_una_cuenta_normal_no_entra_a_ninguna_ruta_del_admin(client: TestClient) -> None:
    token = _register(client, f"normal-{uuid.uuid4().hex[:10]}@ejemplo.com")["access_token"]
    rutas = [(m, r) for m, r in _rutas() if r.startswith("/admin")]
    assert rutas
    abiertas = []
    for metodo, ruta in rutas:
        r = client.request(metodo, _url(ruta, {}), headers=auth(token), json=_cuerpo(metodo))
        if r.status_code != 403:
            abiertas.append(f"{metodo} {ruta} -> {r.status_code}")
    assert abiertas == []


# Cuerpos validos: con uno vacio la ruta responderia 422 antes de buscar la mesa,
# y el test no probaria nada.
_CUERPOS_DE_LA_MESA = {
    ("PATCH", "/sessions/{session_id}"): {"name": "de otra cuenta"},
    ("POST", "/sessions/{session_id}/spins"): {"result_value": "1"},
    ("POST", "/sessions/{session_id}/spins/bulk"): {"values": ["1", "2"], "order": "most_recent_last"},
    ("POST", "/sessions/{session_id}/bets"): {"category": "color", "option_label": "red", "amount": 1000},
}


def test_otra_cuenta_no_ve_ni_toca_nada_de_una_mesa_ajena(
    client: TestClient,
    variant_id: str,  # noqa: F811
) -> None:
    duena = _register(client, f"duena-{uuid.uuid4().hex[:10]}@ejemplo.com")["access_token"]
    otra = _register(client, f"otra-{uuid.uuid4().hex[:10]}@ejemplo.com")["access_token"]
    sesion = _crear_sesion(client, duena, variant_id).json()["id"]
    client.post(
        f"/sessions/{sesion}/spins/bulk",
        json={"values": ["1", "2", "3"] * 4, "order": "most_recent_last"},
        headers=auth(duena),
    )
    apuesta = client.post(
        f"/sessions/{sesion}/bets",
        json={"category": "color", "option_label": "red", "amount": 1000},
        headers=auth(duena),
    )
    assert apuesta.status_code == 201
    giros = client.get(f"/sessions/{sesion}/spins", headers=auth(duena)).json()
    ids = {"session_id": sesion, "spin_id": giros[-1]["id"], "bet_id": apuesta.json()["id"]}
    antes = client.get(f"/sessions/{sesion}", headers=auth(duena)).json()

    rutas = [(m, r) for m, r in _rutas() if "{session_id}" in r]
    assert len(rutas) >= 15
    abiertas = []
    for metodo, ruta in rutas:
        cuerpo = _CUERPOS_DE_LA_MESA.get((metodo, ruta), _cuerpo(metodo))
        r = client.request(metodo, _url(ruta, ids), headers=auth(otra), json=cuerpo)
        if r.status_code != 404:
            abiertas.append(f"{metodo} {ruta} -> {r.status_code}")
    assert abiertas == []

    # Y la mesa de la duena quedo como estaba.
    assert client.get(f"/sessions/{sesion}", headers=auth(duena)).json() == antes
    assert len(client.get(f"/sessions/{sesion}/spins", headers=auth(duena)).json()) == 12
    assert len(client.get(f"/sessions/{sesion}/bets", headers=auth(duena)).json()) == 1


def test_los_campos_que_no_le_tocan_al_cliente_se_ignoran(
    client: TestClient,
    variant_id: str,  # noqa: F811
) -> None:
    email = f"campos-{uuid.uuid4().hex[:10]}@ejemplo.com"
    registro = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "clave-segura-123",
            "role": "admin",
            "access_type": "full",
            "email_verified": True,
            "token_version": 99,
            **consent_fields(client),
        },
    )
    assert registro.status_code == 201
    token = registro.json()["access_token"]
    yo = client.get("/auth/me", headers=auth(token)).json()
    assert yo["role"] == "user"
    assert yo["email_verified"] is False
    acceso_inicial = yo["access_type"]

    client.patch(
        "/auth/me",
        json={"display_name": "Ana", "role": "admin", "access_type": "full", "email": "otro@ejemplo.com"},
        headers=auth(token),
    )
    yo = client.get("/auth/me", headers=auth(token)).json()
    assert (yo["role"], yo["access_type"], yo["email"], yo["display_name"]) == (
        "user",
        acceso_inicial,
        email,
        "Ana",
    )

    # Una mesa siempre es de quien la abre, con la banca que dice el servidor.
    otra = _register(client, f"otra-{uuid.uuid4().hex[:10]}@ejemplo.com")["access_token"]
    id_otra = client.get("/auth/me", headers=auth(otra)).json()["id"]
    mesa = _crear_sesion(
        client, token, variant_id, user_id=id_otra, bankroll_current=999_999_999, status="closed"
    ).json()
    assert mesa["user_id"] == yo["id"]
    assert mesa["bankroll_current"] == mesa["bankroll_start"]
    assert mesa["status"] == "active"
    assert client.get(f"/sessions/{mesa['id']}", headers=auth(otra)).status_code == 404


def test_la_api_manda_sus_cabeceras_de_seguridad(client: TestClient) -> None:
    r = client.get("/health")
    assert r.headers["strict-transport-security"] == "max-age=31536000"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    # Los errores tambien.
    assert client.get("/auth/me").headers["x-content-type-options"] == "nosniff"
    # La documentacion es HTML que carga sus recursos: sin la CSP de JSON.
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "content-security-policy" not in docs.headers
    assert docs.headers["x-frame-options"] == "DENY"


def test_la_busqueda_de_juegos_toma_los_comodines_literales(
    client: TestClient, admin_token: str
) -> None:
    todos = client.get("/admin/games", headers=auth(admin_token)).json()["total"]
    assert todos > 0
    assert client.get("/admin/games", params={"q": "%"}, headers=auth(admin_token)).json()["total"] == 0
    assert client.get("/admin/games", params={"q": "_"}, headers=auth(admin_token)).json()["total"] == 0
