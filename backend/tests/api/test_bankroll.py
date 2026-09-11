"""Tests de integracion de la gestion de banca (paso 7).

Las progresiones ya tienen sus tests puros en `tests/engine/test_bankroll.py`,
con las tablas del documento verificado. Aqui solo se comprueba que la capa HTTP
lee bien el estado de la sesion, respeta el aislamiento por usuario y no pierde
campos al mapear al schema.
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
        },
        {
            # Categoria de pago 2:1: es la que habilita el modo dos-sectores.
            "id": "tercio",
            "label": "Tercio",
            "shrinkage_alpha": 8,
            "groups": {
                "t1": {"label": "Bajo", "outcomes": ["1", "2"], "payout": 2},
                "t2": {"label": "Medio", "outcomes": ["3", "4"], "payout": 2},
                "t3": {"label": "Alto", "outcomes": ["5", "6"], "payout": 2},
            },
        },
    ],
}


def _crear_sesion(
    client: TestClient,
    user_token: str,
    admin_token: str,
    *,
    strategy: str = "martingale",
    strategy_mode: str = "single",
    base_bet: float = 100,
    bankroll: float = 100_000,
    table_limit: float = 500_000,
    loss_limit: float | None = None,
) -> str:
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
            "bankroll_start": bankroll,
            "base_bet": base_bet,
            "table_limit": table_limit,
            "strategy": strategy,
            "strategy_mode": strategy_mode,
            "loss_limit": loss_limit,
        },
        headers=auth(user_token),
    ).json()["id"]


@pytest.fixture
def sesion_martingala(client: TestClient, user_token: str, admin_token: str) -> str:
    return _crear_sesion(client, user_token, admin_token)


# ---------- Sugerencia de banca ----------


def test_la_sugerencia_arranca_en_la_apuesta_base(
    client: TestClient, user_token: str, sesion_martingala: str
) -> None:
    r = client.get(
        f"/sessions/{sesion_martingala}/bankroll/suggestion", headers=auth(user_token)
    )
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["strategy"] == "martingale"
    assert cuerpo["stage"] == 0
    assert cuerpo["suggested_bet"] == 100
    assert cuerpo["sectors"] == 1
    assert cuerpo["cumulative_risked"] == 100


def test_la_sugerencia_trae_el_siguiente_paso_en_los_dos_casos(
    client: TestClient, user_token: str, sesion_martingala: str
) -> None:
    cuerpo = client.get(
        f"/sessions/{sesion_martingala}/bankroll/suggestion", headers=auth(user_token)
    ).json()
    assert cuerpo["next_if_lost"]["stage"] == 1
    assert cuerpo["next_if_lost"]["suggested_bet"] == 200
    assert cuerpo["next_if_lost"]["bankroll_after"] == 99_900
    assert cuerpo["next_if_won"]["stage"] == 0
    assert cuerpo["next_if_won"]["bankroll_after"] == 100_100
    # $100.000 cubren 9 escalones de la tabla ($51.100); el 10 ya exige $102.300.
    assert cuerpo["stages_supported"] == 9
    assert cuerpo["alerts"] == []


def test_la_sugerencia_alerta_cuando_la_banca_queda_corta(
    client: TestClient, user_token: str, admin_token: str
) -> None:
    sid = _crear_sesion(client, user_token, admin_token, bankroll=150)
    alertas = client.get(
        f"/sessions/{sid}/bankroll/suggestion", headers=auth(user_token)
    ).json()["alerts"]
    assert alertas[0]["code"] == "last_affordable_stage"
    assert alertas[0]["level"] == "critical"
    assert alertas[0]["message"]


def test_la_sugerencia_usa_el_limite_de_perdida_de_la_sesion(
    client: TestClient, user_token: str, admin_token: str
) -> None:
    """Con $300 de limite, perder el primer escalon ($100) no lo alcanza; el
    segundo ($200) si."""
    sid = _crear_sesion(client, user_token, admin_token, loss_limit=300)
    cuerpo = client.get(
        f"/sessions/{sid}/bankroll/suggestion", headers=auth(user_token)
    ).json()
    assert cuerpo["next_if_lost"]["reaches_loss_limit"] is False
    assert cuerpo["alerts"] == []

    client.post(
        f"/sessions/{sid}/bets",
        json={"category": "color", "option_label": "Rojo", "amount": 100},
        headers=auth(user_token),
    )
    client.post(
        f"/sessions/{sid}/spins", json={"result_value": "2"}, headers=auth(user_token)
    )
    cuerpo = client.get(
        f"/sessions/{sid}/bankroll/suggestion", headers=auth(user_token)
    ).json()
    assert cuerpo["next_if_lost"]["reaches_loss_limit"] is True
    assert cuerpo["alerts"][0]["code"] == "loss_limit_next"


def test_la_sugerencia_siempre_trae_el_disclaimer_de_la_progresion(
    client: TestClient, user_token: str, sesion_martingala: str
) -> None:
    cuerpo = client.get(
        f"/sessions/{sesion_martingala}/bankroll/suggestion", headers=auth(user_token)
    ).json()
    texto = cuerpo["disclaimer"].lower()
    assert "ninguna progresion" in texto
    assert "ventaja de la casa" in texto


def test_sin_probabilidad_no_se_estima_el_riesgo_de_ruina(
    client: TestClient, user_token: str, sesion_martingala: str
) -> None:
    """El motor no decide a que se apuesta, asi que no inventa la probabilidad."""
    cuerpo = client.get(
        f"/sessions/{sesion_martingala}/bankroll/suggestion", headers=auth(user_token)
    ).json()
    assert cuerpo["ruin_probability_estimate"] is None


def test_al_elegir_una_apuesta_se_estima_el_riesgo(
    client: TestClient, user_token: str, sesion_martingala: str
) -> None:
    cuerpo = client.get(
        f"/sessions/{sesion_martingala}/bankroll/suggestion",
        params={"bet": "color:red"},
        headers=auth(user_token),
    ).json()
    assert 0.0 < cuerpo["ruin_probability_estimate"] < 1.0


def test_una_apuesta_incompatible_con_el_modo_es_rechazada(
    client: TestClient, user_token: str, sesion_martingala: str
) -> None:
    """La sesion es de modo 1:1, asi que 'green' (pago 6) no es elegible."""
    r = client.get(
        f"/sessions/{sesion_martingala}/bankroll/suggestion",
        params={"bet": "color:green"},
        headers=auth(user_token),
    )
    assert r.status_code == 422


def test_lista_las_apuestas_elegibles_del_modo(
    client: TestClient, user_token: str, sesion_martingala: str
) -> None:
    """Modo 1:1: solo los grupos de pago par, nunca el verde de pago 6."""
    apuestas = client.get(
        f"/sessions/{sesion_martingala}/bankroll/eligible-bets",
        headers=auth(user_token),
    ).json()
    assert {a["id"] for a in apuestas} == {"color:red", "color:black"}
    for a in apuestas:
        assert a["theoretical_probability"] == pytest.approx(3 / 7, abs=0.0001)


def test_ganar_con_martingala_deja_una_apuesta_base(
    client: TestClient, user_token: str, sesion_martingala: str
) -> None:
    cuerpo = client.get(
        f"/sessions/{sesion_martingala}/bankroll/suggestion", headers=auth(user_token)
    ).json()
    assert cuerpo["net_result_if_won"] == 100
    assert cuerpo["recovers_only_to_break_even"] is False


# ---------- Tabla de progresion de la sesion ----------


def test_la_tabla_de_la_sesion_reproduce_la_martingala_del_documento(
    client: TestClient, user_token: str, sesion_martingala: str
) -> None:
    cuerpo = client.get(
        f"/sessions/{sesion_martingala}/bankroll/progression",
        params={"stages": 10},
        headers=auth(user_token),
    ).json()
    acumulados = [f["cumulative_loss"] for f in cuerpo["rows"]]
    assert acumulados == [100, 300, 700, 1500, 3100, 6300, 12700, 25500, 51100, 102300]


def test_la_tabla_marca_donde_la_banca_no_alcanza(
    client: TestClient, user_token: str, admin_token: str
) -> None:
    sid = _crear_sesion(
        client, user_token, admin_token, base_bet=100, bankroll=10_000
    )
    cuerpo = client.get(
        f"/sessions/{sid}/bankroll/progression",
        params={"stages": 10},
        headers=auth(user_token),
    ).json()
    superan = [f["stage"] for f in cuerpo["rows"] if f["exceeds_bankroll"]]
    assert superan[0] == 6
    assert cuerpo["max_affordable_stages"] == 6


def test_la_tabla_marca_donde_la_mesa_no_acepta(
    client: TestClient, user_token: str, admin_token: str
) -> None:
    sid = _crear_sesion(
        client, user_token, admin_token, base_bet=100, table_limit=5_000
    )
    cuerpo = client.get(
        f"/sessions/{sid}/bankroll/progression",
        params={"stages": 10},
        headers=auth(user_token),
    ).json()
    superan = [f["stage"] for f in cuerpo["rows"] if f["exceeds_table_limit"]]
    assert superan[0] == 6


def test_no_se_pueden_pedir_escalones_sin_limite(
    client: TestClient, user_token: str, sesion_martingala: str
) -> None:
    r = client.get(
        f"/sessions/{sesion_martingala}/bankroll/progression",
        params={"stages": 500},
        headers=auth(user_token),
    )
    assert r.status_code == 422


# ---------- Modo dos-sectores ----------


def test_la_sesion_de_dos_sectores_devuelve_apuesta_por_sector(
    client: TestClient, user_token: str, admin_token: str
) -> None:
    sid = _crear_sesion(
        client,
        user_token,
        admin_token,
        strategy="two_sector_recovery",
        strategy_mode="two_sector",
        base_bet=100,
    )
    cuerpo = client.get(
        f"/sessions/{sid}/bankroll/suggestion", headers=auth(user_token)
    ).json()
    assert cuerpo["sectors"] == 2
    assert cuerpo["bet_per_sector"] == 100
    assert cuerpo["suggested_bet"] == 200


def test_la_tabla_de_dos_sectores_reproduce_el_documento(
    client: TestClient, user_token: str, admin_token: str
) -> None:
    sid = _crear_sesion(
        client,
        user_token,
        admin_token,
        strategy="two_sector_recovery",
        strategy_mode="two_sector",
        base_bet=100,
    )
    cuerpo = client.get(
        f"/sessions/{sid}/bankroll/progression",
        params={"stages": 5},
        headers=auth(user_token),
    ).json()
    assert [f["bet_per_sector"] for f in cuerpo["rows"]] == [100, 200, 600, 1800, 5400]
    assert [f["total_bet"] for f in cuerpo["rows"]] == [200, 400, 1200, 3600, 10800]
    assert [f["cumulative_loss"] for f in cuerpo["rows"]] == [200, 600, 1800, 5400, 16200]


# ---------- Vista previa sin sesion (§2.8: antes de activar) ----------


def test_la_vista_previa_no_necesita_sesion(
    client: TestClient, user_token: str
) -> None:
    cuerpo = client.get(
        "/bankroll/progression",
        params={
            "strategy": "two_sector_recovery",
            "base_bet": 100,
            "bankroll": 100000,
            "stages": 5,
        },
        headers=auth(user_token),
    ).json()
    assert [f["cumulative_loss"] for f in cuerpo["rows"]] == [200, 600, 1800, 5400, 16200]
    assert cuerpo["disclaimer"]


def test_la_vista_previa_rechaza_apuesta_base_no_positiva(
    client: TestClient, user_token: str
) -> None:
    r = client.get(
        "/bankroll/progression",
        params={"strategy": "flat", "base_bet": 0, "bankroll": 1000},
        headers=auth(user_token),
    )
    assert r.status_code == 422


def test_la_vista_previa_rechaza_una_estrategia_inexistente(
    client: TestClient, user_token: str
) -> None:
    r = client.get(
        "/bankroll/progression",
        params={"strategy": "sistema_infalible", "base_bet": 100, "bankroll": 1000},
        headers=auth(user_token),
    )
    assert r.status_code == 422


# ---------- Aislamiento y autenticacion ----------


def test_no_se_ve_la_banca_de_una_sesion_ajena(
    client: TestClient, sesion_martingala: str
) -> None:
    otro = client.post(
        "/auth/register",
        json={
            "email": f"otro-{uuid.uuid4().hex[:10]}@ejemplo.com",
            "password": "clave-segura-123",
        },
    ).json()["access_token"]

    for ruta in ("bankroll/suggestion", "bankroll/progression"):
        r = client.get(f"/sessions/{sesion_martingala}/{ruta}", headers=auth(otro))
        assert r.status_code == 404


def test_sesion_inexistente_da_404(client: TestClient, user_token: str) -> None:
    r = client.get(
        f"/sessions/{uuid.uuid4()}/bankroll/suggestion", headers=auth(user_token)
    )
    assert r.status_code == 404


def test_requiere_autenticacion(client: TestClient, sesion_martingala: str) -> None:
    assert (
        client.get(f"/sessions/{sesion_martingala}/bankroll/suggestion").status_code
        == 401
    )
    assert client.get("/bankroll/progression").status_code == 401


def test_las_apuestas_elegibles_de_dos_sectores_son_parejas(
    client: TestClient, user_token: str, admin_token: str
) -> None:
    sid = _crear_sesion(
        client,
        user_token,
        admin_token,
        strategy="two_sector_recovery",
        strategy_mode="two_sector",
    )
    apuestas = client.get(
        f"/sessions/{sid}/bankroll/eligible-bets", headers=auth(user_token)
    ).json()
    assert {a["id"] for a in apuestas} == {
        "tercio:t1+t2",
        "tercio:t1+t3",
        "tercio:t2+t3",
    }
    for a in apuestas:
        assert a["theoretical_probability"] == pytest.approx(4 / 7, abs=0.0001)


def test_ganar_en_dos_sectores_solo_recupera_desde_el_segundo_escalon(
    client: TestClient, user_token: str, admin_token: str
) -> None:
    """Punto que la UI debe decir explicitamente: recupera, no deja ganancia."""
    sid = _crear_sesion(
        client,
        user_token,
        admin_token,
        strategy="two_sector_recovery",
        strategy_mode="two_sector",
        base_bet=100,
    )
    # Escalon 1: si deja ganancia.
    primero = client.get(
        f"/sessions/{sid}/bankroll/suggestion", headers=auth(user_token)
    ).json()
    assert primero["net_result_if_won"] == 100
    assert primero["recovers_only_to_break_even"] is False
