"""Flujo de sesion de mesa con ingreso manual (pasos 5 y 8).

Crea la sesion por la API, registra giros uno a uno, carga de una vez los ya
observados, deshace, cierra, y comprueba las reglas de §2.8, §3.5 y §3.6.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import auth

RULETA_MINI = {
    "possible_outcomes": ["0", "1", "2", "3", "4", "5", "6"],
    "categories": [
        {
            "id": "color",
            "label": "Color",
            "shrinkage_alpha": 8,
            "groups": {
                "red": {"label": "Rojo", "outcomes": ["1", "3", "5"], "payout": 1},
                "black": {"label": "Negro", "outcomes": ["2", "4", "6"], "payout": 1},
                "green": {"label": "Verde", "outcomes": ["0"], "payout": 6},
            },
        }
    ],
}


@pytest.fixture
def variant_id(client: TestClient, admin_token: str) -> str:
    sufijo = uuid.uuid4().hex[:8]
    game = client.post(
        "/admin/games",
        json={"name": f"Ruleta {sufijo}", "type": f"roulette_{sufijo}", "active": True},
        headers=auth(admin_token),
    ).json()
    return client.post(
        f"/admin/games/{game['id']}/variants",
        json={"name": "mini", "house_edge": 0.1429, "config": RULETA_MINI},
        headers=auth(admin_token),
    ).json()["id"]


@pytest.fixture
def sesion(client: TestClient, user_token: str, variant_id: str) -> str:
    """Una sesion abierta y vacia, lista para registrar giros."""
    return _crear_sesion(client, user_token, variant_id).json()["id"]


def _listar(client: TestClient, token: str, session_id: str) -> list[dict]:
    """Giros de la sesion, en orden cronologico ascendente."""
    return client.get(f"/sessions/{session_id}/spins", headers=auth(token)).json()


def _crear_sesion(client: TestClient, token: str, variant_id: str, **extra) -> dict:
    body = {
        "game_variant_id": variant_id,
        "name": "Mesa 1",
        "window_size": 50,
        "bankroll_start": 100000,
        "base_bet": 1000,
        "table_limit": 500000,
        "strategy": "flat",
        "strategy_mode": "single",
        **extra,
    }
    return client.post("/sessions", json=body, headers=auth(token))


# ---------- Crear sesion ----------


def test_crear_sesion_inicializa_la_banca(
    client: TestClient, user_token: str, variant_id: str
) -> None:
    r = _crear_sesion(client, user_token, variant_id)
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["status"] == "active"
    assert s["name"] == "Mesa 1"
    # La banca actual arranca igual a la inicial.
    assert s["bankroll_current"] == s["bankroll_start"] == 100000.0
    assert s["strategy_stage"] == 0


def test_apuesta_base_mayor_que_la_banca_es_rechazada(
    client: TestClient, user_token: str, variant_id: str
) -> None:
    """`validate_bet_within_bankroll` es un metodo del schema, no un validador
    automatico: si el endpoint no lo llama, no corre."""
    r = _crear_sesion(client, user_token, variant_id, bankroll_start=1000, base_bet=5000)
    assert r.status_code == 422
    assert "no puede superar" in r.text


def test_modo_dos_sectores_con_estrategia_incoherente_es_rechazado(
    client: TestClient, user_token: str, variant_id: str
) -> None:
    """§2.8, validado por el schema antes de llegar a la base."""
    r = _crear_sesion(client, user_token, variant_id, strategy_mode="two_sector")
    assert r.status_code == 422
    r = _crear_sesion(client, user_token, variant_id, strategy="two_sector_recovery")
    assert r.status_code == 422


def test_modo_dos_sectores_coherente_se_acepta(
    client: TestClient, user_token: str, variant_id: str
) -> None:
    r = _crear_sesion(
        client, user_token, variant_id,
        strategy="two_sector_recovery", strategy_mode="two_sector",
    )
    assert r.status_code == 201, r.text


def test_variante_inexistente_da_404(client: TestClient, user_token: str) -> None:
    r = _crear_sesion(client, user_token, str(uuid.uuid4()))
    assert r.status_code == 404


def test_variante_inactiva_no_admite_sesiones(
    client: TestClient, user_token: str, admin_token: str, variant_id: str
) -> None:
    sesion = _crear_sesion(client, user_token, variant_id).json()
    game_id = client.get(f"/sessions/{sesion['id']}", headers=auth(user_token)).json()
    juegos = client.get("/games", params={"include_inactive": True}, headers=auth(admin_token)).json()
    juego = next(g for g in juegos if any(v["id"] == variant_id for v in g["variants"]))
    client.patch(
        f"/admin/games/{juego['id']}/variants/{variant_id}",
        json={"active": False}, headers=auth(admin_token),
    )
    assert game_id is not None
    r = _crear_sesion(client, user_token, variant_id)
    assert r.status_code == 404


# ---------- Giros ----------


def test_flujo_completo_de_ingreso_manual(
    client: TestClient, user_token: str, variant_id: str
) -> None:
    """La demo jugable del paso 5: crear sesion, ingresar numeros, deshacer, cerrar."""
    sesion = _crear_sesion(client, user_token, variant_id).json()
    sid = sesion["id"]

    for valor in ["1", "0", "4", "3"]:
        r = client.post(
            f"/sessions/{sid}/spins", json={"result_value": valor}, headers=auth(user_token)
        )
        assert r.status_code == 201, r.text

    r = client.get(f"/sessions/{sid}/spins", headers=auth(user_token))
    giros = r.json()
    # Orden cronologico ascendente, indices consecutivos desde 0.
    assert [g["result_value"] for g in giros] == ["1", "0", "4", "3"]
    assert [g["spin_index"] for g in giros] == [0, 1, 2, 3]
    assert all(g["source"] == "manual" for g in giros)

    # Deshacer el ultimo.
    r = client.delete(f"/sessions/{sid}/spins/{giros[-1]['id']}", headers=auth(user_token))
    assert r.status_code == 204
    giros = client.get(f"/sessions/{sid}/spins", headers=auth(user_token)).json()
    assert [g["result_value"] for g in giros] == ["1", "0", "4"]

    # El siguiente giro retoma el indice liberado, sin dejar huecos.
    client.post(f"/sessions/{sid}/spins", json={"result_value": "6"}, headers=auth(user_token))
    giros = client.get(f"/sessions/{sid}/spins", headers=auth(user_token)).json()
    assert [g["spin_index"] for g in giros] == [0, 1, 2, 3]
    assert giros[-1]["result_value"] == "6"

    r = client.post(f"/sessions/{sid}/close", headers=auth(user_token))
    assert r.status_code == 200
    assert r.json()["status"] == "closed"
    assert r.json()["closed_at"] is not None


def test_resultado_fuera_de_la_variante_es_rechazado(
    client: TestClient, user_token: str, variant_id: str
) -> None:
    sid = _crear_sesion(client, user_token, variant_id).json()["id"]
    r = client.post(
        f"/sessions/{sid}/spins", json={"result_value": "37"}, headers=auth(user_token)
    )
    assert r.status_code == 422
    assert "no es un resultado posible" in r.text


def test_solo_se_puede_deshacer_el_ultimo_giro(
    client: TestClient, user_token: str, variant_id: str
) -> None:
    """Borrar uno del medio dejaria huecos en spin_index y desplazaria el peso
    por recencia (§2.3) de todos los giros posteriores."""
    sid = _crear_sesion(client, user_token, variant_id).json()["id"]
    for valor in ["1", "2", "3"]:
        client.post(f"/sessions/{sid}/spins", json={"result_value": valor}, headers=auth(user_token))
    giros = client.get(f"/sessions/{sid}/spins", headers=auth(user_token)).json()

    r = client.delete(f"/sessions/{sid}/spins/{giros[0]['id']}", headers=auth(user_token))
    assert r.status_code == 409
    assert "ultimo giro" in r.text
    assert len(client.get(f"/sessions/{sid}/spins", headers=auth(user_token)).json()) == 3


def test_giro_de_otra_sesion_no_se_puede_borrar(
    client: TestClient, user_token: str, variant_id: str
) -> None:
    a = _crear_sesion(client, user_token, variant_id).json()["id"]
    b = _crear_sesion(client, user_token, variant_id).json()["id"]
    client.post(f"/sessions/{a}/spins", json={"result_value": "1"}, headers=auth(user_token))
    giro = client.get(f"/sessions/{a}/spins", headers=auth(user_token)).json()[0]

    r = client.delete(f"/sessions/{b}/spins/{giro['id']}", headers=auth(user_token))
    assert r.status_code == 404


def test_sesion_cerrada_no_admite_giros_ni_cambios(
    client: TestClient, user_token: str, variant_id: str
) -> None:
    sid = _crear_sesion(client, user_token, variant_id).json()["id"]
    client.post(f"/sessions/{sid}/close", headers=auth(user_token))

    assert client.post(
        f"/sessions/{sid}/spins", json={"result_value": "1"}, headers=auth(user_token)
    ).status_code == 409
    assert client.patch(
        f"/sessions/{sid}", json={"name": "Otro"}, headers=auth(user_token)
    ).status_code == 409
    assert client.post(f"/sessions/{sid}/close", headers=auth(user_token)).status_code == 409
    # Pero leerla sigue funcionando: es historico.
    assert client.get(f"/sessions/{sid}", headers=auth(user_token)).status_code == 200


def test_no_se_pueden_ingresar_giros_en_sesion_ajena(
    client: TestClient, user_token: str, variant_id: str
) -> None:
    """§3.6: cada consulta filtra por el user_id del token."""
    otro = client.post(
        "/auth/register",
        json={"email": f"otro-{uuid.uuid4().hex[:10]}@ejemplo.com", "password": "clave-segura-123"},
    ).json()["access_token"]
    sid = _crear_sesion(client, user_token, variant_id).json()["id"]

    assert client.post(
        f"/sessions/{sid}/spins", json={"result_value": "1"}, headers=auth(otro)
    ).status_code == 404
    assert client.get(f"/sessions/{sid}/spins", headers=auth(otro)).status_code == 404


# ---------- Renombrar, estrategia, reset ----------


def test_renombrar_sesion(client: TestClient, user_token: str, variant_id: str) -> None:
    sid = _crear_sesion(client, user_token, variant_id).json()["id"]
    r = client.patch(f"/sessions/{sid}", json={"name": "Mesa VIP"}, headers=auth(user_token))
    assert r.status_code == 200
    assert r.json()["name"] == "Mesa VIP"


def test_cambiar_de_estrategia_reinicia_el_escalon(
    client: TestClient, user_token: str, variant_id: str
) -> None:
    sid = _crear_sesion(client, user_token, variant_id).json()["id"]
    r = client.patch(f"/sessions/{sid}", json={"strategy": "martingale"}, headers=auth(user_token))
    assert r.status_code == 200
    assert r.json()["strategy_selected"] == "martingale"
    assert r.json()["strategy_stage"] == 0


def test_cambiar_solo_el_modo_sin_la_estrategia_es_rechazado_con_422(
    client: TestClient, user_token: str, variant_id: str
) -> None:
    """El validador del schema solo cruza ambos si vienen juntos; el endpoint
    tiene que combinar con lo persistido o el CHECK daria un 500."""
    sid = _crear_sesion(client, user_token, variant_id).json()["id"]
    r = client.patch(
        f"/sessions/{sid}", json={"strategy_mode": "two_sector"}, headers=auth(user_token)
    )
    assert r.status_code == 422
    assert "2.8" in r.text or "dos-sectores" in r.text


def test_cambiar_modo_y_estrategia_juntos_si_funciona(
    client: TestClient, user_token: str, variant_id: str
) -> None:
    sid = _crear_sesion(client, user_token, variant_id).json()["id"]
    r = client.patch(
        f"/sessions/{sid}",
        json={"strategy_mode": "two_sector", "strategy": "two_sector_recovery"},
        headers=auth(user_token),
    )
    assert r.status_code == 200
    assert r.json()["strategy_mode"] == "two_sector"


# ---------- Limite de perdida ----------


def test_la_sesion_guarda_el_limite_de_perdida(
    client: TestClient, user_token: str, variant_id: str
) -> None:
    r = _crear_sesion(client, user_token, variant_id, loss_limit=20_000)
    assert r.status_code == 201
    assert r.json()["loss_limit"] == 20_000


def test_el_limite_de_perdida_es_opcional(
    client: TestClient, user_token: str, variant_id: str
) -> None:
    assert _crear_sesion(client, user_token, variant_id).json()["loss_limit"] is None


def test_el_limite_de_perdida_no_puede_superar_la_banca(
    client: TestClient, user_token: str, variant_id: str
) -> None:
    r = _crear_sesion(client, user_token, variant_id, loss_limit=150_000)
    assert r.status_code == 422


def test_se_puede_fijar_y_bajar_el_limite_con_la_sesion_abierta(
    client: TestClient, user_token: str, variant_id: str
) -> None:
    sid = _crear_sesion(client, user_token, variant_id).json()["id"]
    r = client.patch(f"/sessions/{sid}", json={"loss_limit": 30_000}, headers=auth(user_token))
    assert r.status_code == 200
    r = client.patch(f"/sessions/{sid}", json={"loss_limit": 10_000}, headers=auth(user_token))
    assert r.status_code == 200
    assert r.json()["loss_limit"] == 10_000


@pytest.mark.parametrize("nuevo", [40_000, None])
def test_no_se_puede_subir_ni_quitar_el_limite_con_la_sesion_abierta(
    client: TestClient, user_token: str, variant_id: str, nuevo: float | None
) -> None:
    """§9 del documento verificado: no aumentes el limite para recuperar."""
    sid = _crear_sesion(client, user_token, variant_id, loss_limit=20_000).json()["id"]
    r = client.patch(f"/sessions/{sid}", json={"loss_limit": nuevo}, headers=auth(user_token))
    assert r.status_code == 422
    assert "no subir" in r.text
    assert client.get(f"/sessions/{sid}", headers=auth(user_token)).json()["loss_limit"] == 20_000


def test_reset_de_estrategia_no_toca_los_giros(
    client: TestClient, user_token: str, variant_id: str
) -> None:
    sid = _crear_sesion(client, user_token, variant_id).json()["id"]
    client.post(f"/sessions/{sid}/spins", json={"result_value": "1"}, headers=auth(user_token))

    r = client.post(f"/sessions/{sid}/reset-strategy", headers=auth(user_token))
    assert r.status_code == 200
    assert r.json()["strategy_stage"] == 0
    assert len(client.get(f"/sessions/{sid}/spins", headers=auth(user_token)).json()) == 1


# ---------- Carga inicial de numeros (paso 8, §3.5) ----------


def test_carga_inicial_registra_los_numeros_en_orden_cronologico(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """El usuario escribio con el mas reciente primero: se invierte al guardar."""
    r = client.post(
        f"/sessions/{sesion}/spins/bulk",
        json={"values": ["5", "4", "3"], "order": "most_recent_first"},
        headers=auth(user_token),
    )
    assert r.status_code == 201
    assert r.json()["created"] == 3

    valores = [s["result_value"] for s in _listar(client, user_token, sesion)]
    assert valores == ["3", "4", "5"]


def test_carga_inicial_en_orden_cronologico_se_deja_igual(
    client: TestClient, user_token: str, sesion: str
) -> None:
    client.post(
        f"/sessions/{sesion}/spins/bulk",
        json={"values": ["3", "4", "5"], "order": "most_recent_last"},
        headers=auth(user_token),
    )
    valores = [s["result_value"] for s in _listar(client, user_token, sesion)]
    assert valores == ["3", "4", "5"]


def test_los_giros_cargados_se_distinguen_de_los_manuales(
    client: TestClient, user_token: str, sesion: str
) -> None:
    client.post(
        f"/sessions/{sesion}/spins/bulk",
        json={"values": ["1", "2"], "order": "most_recent_last"},
        headers=auth(user_token),
    )
    client.post(
        f"/sessions/{sesion}/spins",
        json={"result_value": "3", "source": "manual"},
        headers=auth(user_token),
    )
    fuentes = [s["source"] for s in _listar(client, user_token, sesion)]
    assert fuentes == ["initial_batch", "initial_batch", "manual"]


def test_la_carga_inicial_continua_la_numeracion_existente(
    client: TestClient, user_token: str, sesion: str
) -> None:
    client.post(
        f"/sessions/{sesion}/spins",
        json={"result_value": "1", "source": "manual"},
        headers=auth(user_token),
    )
    client.post(
        f"/sessions/{sesion}/spins/bulk",
        json={"values": ["2", "3"], "order": "most_recent_last"},
        headers=auth(user_token),
    )
    indices = [s["spin_index"] for s in _listar(client, user_token, sesion)]
    assert indices == [0, 1, 2]


def test_un_valor_ajeno_a_la_variante_rechaza_la_carga_entera(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """No se descartan valores en silencio: falla y dice cual esta mal."""
    r = client.post(
        f"/sessions/{sesion}/spins/bulk",
        json={"values": ["1", "99", "2"], "order": "most_recent_last"},
        headers=auth(user_token),
    )
    assert r.status_code == 422
    assert "99" in r.json()["detail"]["errors"]
    assert _listar(client, user_token, sesion) == []


def test_la_carga_inicial_conserva_los_duplicados(
    client: TestClient, user_token: str, sesion: str
) -> None:
    client.post(
        f"/sessions/{sesion}/spins/bulk",
        json={"values": ["3", "3", "3"], "order": "most_recent_last"},
        headers=auth(user_token),
    )
    valores = [s["result_value"] for s in _listar(client, user_token, sesion)]
    assert valores == ["3", "3", "3"]


def test_el_orden_es_obligatorio(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Adivinarlo invertiria la ponderacion por recencia sin error visible."""
    r = client.post(
        f"/sessions/{sesion}/spins/bulk",
        json={"values": ["1", "2"]},
        headers=auth(user_token),
    )
    assert r.status_code == 422


def test_una_carga_desmedida_se_rechaza(
    client: TestClient, user_token: str, sesion: str
) -> None:
    r = client.post(
        f"/sessions/{sesion}/spins/bulk",
        json={"values": ["1"] * 501, "order": "most_recent_last"},
        headers=auth(user_token),
    )
    assert r.status_code == 422


def test_no_se_puede_cargar_en_una_sesion_ajena(
    client: TestClient, sesion: str
) -> None:
    otro = client.post(
        "/auth/register",
        json={
            "email": f"otro-{uuid.uuid4().hex[:10]}@ejemplo.com",
            "password": "clave-segura-123",
        },
    ).json()["access_token"]
    r = client.post(
        f"/sessions/{sesion}/spins/bulk",
        json={"values": ["1"], "order": "most_recent_last"},
        headers=auth(otro),
    )
    assert r.status_code == 404
