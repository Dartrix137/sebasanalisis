"""Tests de lectura de sesiones (paso 4).

Crear sesiones es del paso 5, asi que las filas se insertan directamente en la
base: lo que se prueba aqui es el aislamiento por usuario y el filtro de estado.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from tests.api.conftest import auth

VARIANT_CONFIG = {
    "possible_outcomes": ["1", "2"],
    "categories": [
        {"id": "x", "label": "X", "groups": {"a": {"outcomes": ["1"], "payout": 1}}}
    ],
}


@pytest.fixture
def variant_id(client: TestClient, admin_token: str) -> str:
    sufijo = uuid.uuid4().hex[:8]
    game = client.post(
        "/admin/games",
        json={"name": f"Juego {sufijo}", "type": f"tipo_{sufijo}", "active": True},
        headers=auth(admin_token),
    ).json()
    return client.post(
        f"/admin/games/{game['id']}/variants",
        json={"name": "v1", "house_edge": 0.027, "config": VARIANT_CONFIG},
        headers=auth(admin_token),
    ).json()["id"]


def _insert_session(
    db_url: str,
    email: str,
    variant_id: str,
    *,
    status: str = "active",
    stage_martingale: int = 0,
    stage_two_sector: int = 0,
) -> str:
    session_id = str(uuid.uuid4())
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO game_sessions (id, user_id, game_variant_id, name, status,"
                " window_size, bankroll_start, bankroll_current, base_bet, table_limit,"
                " stage_martingale, stage_two_sector, started_at)"
                " SELECT :sid, u.id, :vid, 'Mesa 1', :st, 50, 100000, 100000, 1000, 500000,"
                " :mart, :dos, now() FROM users u WHERE u.email = :email"
            ),
            {
                "sid": session_id,
                "vid": variant_id,
                "st": status,
                "mart": stage_martingale,
                "dos": stage_two_sector,
                "email": email,
            },
        )
    engine.dispose()
    return session_id


@pytest.fixture
def owner(client: TestClient) -> dict:
    email = f"duenio-{uuid.uuid4().hex[:10]}@ejemplo.com"
    tokens = client.post(
        "/auth/register", json={"email": email, "password": "clave-segura-123"}
    ).json()
    return {"email": email, "token": tokens["access_token"]}


def test_lista_vacia_para_usuario_nuevo(client: TestClient, user_token: str) -> None:
    r = client.get("/sessions", headers=auth(user_token))
    assert r.status_code == 200
    assert r.json() == []


def test_lista_las_sesiones_del_usuario(
    client: TestClient, test_database: str, owner: dict, variant_id: str
) -> None:
    sid = _insert_session(test_database, owner["email"], variant_id)

    r = client.get("/sessions", headers=auth(owner["token"]))
    assert r.status_code == 200, r.text
    sesiones = r.json()
    assert [s["id"] for s in sesiones] == [sid]
    s = sesiones[0]
    assert s["status"] == "active"
    assert s["name"] == "Mesa 1"
    assert s["stage_martingale"] == 0
    assert s["stage_two_sector"] == 0
    assert s["bankroll_current"] == 100000.0
    assert s["window_size"] == 50


def test_filtro_por_estado(
    client: TestClient, test_database: str, owner: dict, variant_id: str
) -> None:
    abierta = _insert_session(test_database, owner["email"], variant_id, status="active")
    _insert_session(test_database, owner["email"], variant_id, status="closed")

    r = client.get("/sessions", params={"status": "active"}, headers=auth(owner["token"]))
    assert [s["id"] for s in r.json()] == [abierta]

    r = client.get("/sessions", params={"status": "closed"}, headers=auth(owner["token"]))
    assert len(r.json()) == 1

    assert len(client.get("/sessions", headers=auth(owner["token"])).json()) == 2


def test_estado_invalido_es_rechazado(client: TestClient, user_token: str) -> None:
    r = client.get("/sessions", params={"status": "pausada"}, headers=auth(user_token))
    assert r.status_code == 422


def test_no_se_ven_sesiones_de_otro_usuario(
    client: TestClient, test_database: str, owner: dict, user_token: str, variant_id: str
) -> None:
    """§3.6: cada consulta filtra por el user_id del token."""
    sid = _insert_session(test_database, owner["email"], variant_id)

    assert client.get("/sessions", headers=auth(user_token)).json() == []
    # Y pedirla por id devuelve 404, no 403: confirmar que existe ya seria una fuga.
    assert client.get(f"/sessions/{sid}", headers=auth(user_token)).status_code == 404
    assert client.get(f"/sessions/{sid}", headers=auth(owner["token"])).status_code == 200


def test_sesiones_requieren_autenticacion(client: TestClient) -> None:
    assert client.get("/sessions").status_code == 401
    assert client.get(f"/sessions/{uuid.uuid4()}").status_code == 401


def test_sesion_inexistente_da_404(client: TestClient, user_token: str) -> None:
    r = client.get(f"/sessions/{uuid.uuid4()}", headers=auth(user_token))
    assert r.status_code == 404


def test_un_escalon_negativo_es_rechazado_por_la_base(
    test_database: str, owner: dict, variant_id: str
) -> None:
    """El CHECK que reemplaza al de modo/estrategia: los escalones son
    contadores de progresion y no pueden ir hacia atras de cero."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        _insert_session(test_database, owner["email"], variant_id, stage_martingale=-1)


def test_los_dos_escalones_viajan_en_la_respuesta(
    client: TestClient, test_database: str, owner: dict, variant_id: str
) -> None:
    """Las tres progresiones corren a la vez, asi que cada una expone el suyo
    (la plana no tiene: siempre esta en 0)."""
    sid = _insert_session(
        test_database, owner["email"], variant_id, stage_martingale=3, stage_two_sector=2
    )
    r = client.get(f"/sessions/{sid}", headers=auth(owner["token"]))
    assert r.status_code == 200
    assert r.json()["stage_martingale"] == 3
    assert r.json()["stage_two_sector"] == 2
