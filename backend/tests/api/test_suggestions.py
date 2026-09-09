"""Tests de integracion de las senales estadisticas (paso 6).

El motor ya tiene sus 97 tests puros en `tests/engine/`. Aqui solo se comprueba
que la capa HTTP carga bien los giros, respeta el aislamiento por usuario y mapea
al schema sin perder campos.
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
def sesion(client: TestClient, user_token: str, admin_token: str) -> str:
    sufijo = uuid.uuid4().hex[:8]
    game = client.post(
        "/admin/games",
        json={"name": f"Ruleta {sufijo}", "type": f"roulette_{sufijo}", "active": True},
        headers=auth(admin_token),
    ).json()
    variant = client.post(
        f"/admin/games/{game['id']}/variants",
        json={"name": "mini", "house_edge": 0.1429, "config": RULETA_MINI},
        headers=auth(admin_token),
    ).json()
    return client.post(
        "/sessions",
        json={
            "game_variant_id": variant["id"],
            "window_size": 50,
            "bankroll_start": 100000,
            "base_bet": 1000,
            "table_limit": 500000,
            "strategy": "flat",
            "strategy_mode": "single",
        },
        headers=auth(user_token),
    ).json()["id"]


def _ingresar(client: TestClient, token: str, sid: str, valores: list[str]) -> None:
    for v in valores:
        client.post(f"/sessions/{sid}/spins", json={"result_value": v}, headers=auth(token))


# ---------- Panel de senales ----------


def test_sesion_sin_giros_devuelve_las_teoricas(
    client: TestClient, user_token: str, sesion: str
) -> None:
    r = client.get(f"/sessions/{sesion}/suggestions/latest", headers=auth(user_token))
    assert r.status_code == 200, r.text
    panel = r.json()
    assert panel["window_size_used"] == 50
    assert len(panel["top"]) == 3
    for item in panel["all_categories"]["color"]:
        assert item["observed_frequency_shrunk"] == pytest.approx(
            item["theoretical_probability"]
        )
        assert item["deviation"] == pytest.approx(0.0)


def test_cada_senal_trae_teorica_y_observada(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Regla anti-falacia del jugador (§2): nunca una sin la otra."""
    _ingresar(client, user_token, sesion, ["1", "3", "5", "1", "3"])
    panel = client.get(
        f"/sessions/{sesion}/suggestions/latest", headers=auth(user_token)
    ).json()

    for item in panel["top"]:
        assert "theoretical_probability" in item
        assert "observed_frequency_shrunk" in item
        assert item["strength"] in {"strong", "medium", "weak"}
        assert isinstance(item["ev"], float)


def test_con_pocos_giros_ninguna_senal_es_fuerte(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """FUERTE exige respaldo de chi-cuadrado, que necesita 36 giros minimo."""
    _ingresar(client, user_token, sesion, ["1", "3", "5", "1", "3", "5"])
    panel = client.get(
        f"/sessions/{sesion}/suggestions/latest", headers=auth(user_token)
    ).json()
    todas = [i for grupo in panel["all_categories"].values() for i in grupo]
    assert all(i["strength"] != "strong" for i in todas)
    assert all(i["chi_square_pvalue"] is None for i in todas)


def test_con_sesgo_marcado_y_volumen_aparece_el_pvalue(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _ingresar(client, user_token, sesion, ["1"] * 40)
    panel = client.get(
        f"/sessions/{sesion}/suggestions/latest", headers=auth(user_token)
    ).json()
    rojo = next(i for i in panel["all_categories"]["color"] if i["option_label"] == "Rojo")
    assert rojo["chi_square_pvalue"] is not None
    assert rojo["chi_square_pvalue"] < 0.05
    assert rojo["observed_frequency_shrunk"] > rojo["theoretical_probability"]


# ---------- Racha ----------


def test_sin_racha_devuelve_null(client: TestClient, user_token: str, sesion: str) -> None:
    r = client.get(f"/sessions/{sesion}/streak", headers=auth(user_token))
    assert r.status_code == 200
    assert r.json() is None


def test_racha_activa(client: TestClient, user_token: str, sesion: str) -> None:
    _ingresar(client, user_token, sesion, ["2", "1", "3", "5"])
    racha = client.get(f"/sessions/{sesion}/streak", headers=auth(user_token)).json()
    assert racha["option_label"] == "Rojo"
    assert racha["consecutive_count"] == 3
    assert racha["probability_of_streak"] == pytest.approx((3 / 7) ** 3, abs=1e-9)


# ---------- Auto-evaluacion ----------


def test_auto_evaluacion_compara_contra_la_linea_base(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _ingresar(client, user_token, sesion, ["1", "2", "3", "4", "5", "0", "6", "1"])
    r = client.get(f"/sessions/{sesion}/performance", headers=auth(user_token))
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["total_suggestions"] > 0
    assert p["baseline_suggestions" if "baseline_suggestions" in p else "baseline_matched"] is not None
    assert 0 <= p["match_rate"] <= 1
    assert 0 <= p["baseline_match_rate"] <= 1
    assert p["verdict"]


def test_el_veredicto_no_usa_lenguaje_predictivo(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _ingresar(client, user_token, sesion, ["1", "2", "3", "4", "5", "0", "6"])
    veredicto = client.get(
        f"/sessions/{sesion}/performance", headers=auth(user_token)
    ).json()["verdict"].lower()
    for prohibida in ("predic", "va a salir", "acierto", "precision", "garantiz"):
        assert prohibida not in veredicto


# ---------- Aislamiento ----------


def test_no_se_ven_senales_de_sesion_ajena(
    client: TestClient, user_token: str, sesion: str
) -> None:
    otro = client.post(
        "/auth/register",
        json={"email": f"otro-{uuid.uuid4().hex[:10]}@ejemplo.com", "password": "clave-segura-123"},
    ).json()["access_token"]

    for ruta in ("suggestions/latest", "streak", "performance"):
        assert client.get(f"/sessions/{sesion}/{ruta}", headers=auth(otro)).status_code == 404


def test_requieren_autenticacion(client: TestClient, sesion: str) -> None:
    for ruta in ("suggestions/latest", "streak", "performance"):
        assert client.get(f"/sessions/{sesion}/{ruta}").status_code == 401
