"""Tests de integracion del motor de recomendacion (§2.10).

El motor tiene sus tests puros en `tests/engine/test_recommendation.py`. Aqui se
comprueba lo que solo existe con base de datos: que la recomendacion se persista,
que se resuelva con el giro siguiente, que las progresiones avancen con ella y no
con las apuestas reales, y que deshacer un giro deshaga tambien su recomendacion.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.engine.recommendation import WEIGHT_DEVIATION, WEIGHT_RECENCY
from tests.api.conftest import auth

#: Ruleta reducida con dos categorias de pago 1:1 y una de 2:1, mas una
#: combinacion permitida: lo minimo para ejercitar mercados simples y dobles.
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
                # Igual que el verde de la ruleta: cubre el 0 y no es mercado.
                "green": {
                    "label": "Verde",
                    "outcomes": ["0"],
                    "payout": 6,
                    "market": False,
                },
            },
        },
        {
            "id": "tercio",
            "label": "Tercio",
            "shrinkage_alpha": 12,
            "groups": {
                "t1": {"label": "Bajo", "outcomes": ["1", "2"], "payout": 2},
                "t2": {"label": "Medio", "outcomes": ["3", "4"], "payout": 2},
                "t3": {"label": "Alto", "outcomes": ["5", "6"], "payout": 2},
            },
        },
    ],
    "allowed_combinations": [
        {
            "id": "tercio:t1+t2",
            "label": "Bajo + Medio",
            "category_id": "tercio",
            "group_ids": ["t1", "t2"],
        },
    ],
    "recommendation_threshold": 60,
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
    assert "id" in variant, variant
    return client.post(
        "/sessions",
        json={
            "game_variant_id": variant["id"],
            "window_size": 50,
            "bankroll_start": 100_000,
            "base_bet": 1_000,
            "table_limit": 500_000,
        },
        headers=auth(user_token),
    ).json()["id"]


def _girar(client, token, sid, valor):
    return client.post(
        f"/sessions/{sid}/spins",
        json={"result_value": valor, "source": "manual"},
        headers=auth(token),
    )


def _recomendacion(client, token, sid):
    r = client.get(f"/sessions/{sid}/recommendation", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _historial(client, token, sid):
    r = client.get(f"/sessions/{sid}/recommendation/history", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _sesion(client, token, sid):
    return client.get(f"/sessions/{sid}", headers=auth(token)).json()


# ---------- Forma de la respuesta ----------


def test_una_mesa_vacia_no_recomienda(client: TestClient, user_token: str, sesion: str) -> None:
    cuerpo = _recomendacion(client, user_token, sesion)
    assert cuerpo["decision"] == "NO_BET"
    assert cuerpo["market"] is None
    assert cuerpo["stakes"] == []
    assert cuerpo["total_spins"] == 0
    assert cuerpo["threshold"] == 60
    assert cuerpo["strong_threshold"] == 80
    assert cuerpo["signal_band"] == "weak"


def test_la_banda_de_la_respuesta_sigue_a_la_decision(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Tres estados de salida (§2.10): con recomendacion la banda es MEDIA o
    FUERTE, sin ella SIN SEÑAL — tambien en lo que queda guardado."""
    for valor in ["1", "3", "5", "7", "9", "12", "14", "16", "18", "19", "21", "23"]:
        _girar(client, user_token, sesion, valor)
        cuerpo = _recomendacion(client, user_token, sesion)
        if cuerpo["decision"] == "RECOMMEND":
            esperada = "strong" if cuerpo["signal_score"] >= cuerpo["strong_threshold"] else "medium"
        else:
            esperada = "weak"
        assert cuerpo["signal_band"] == esperada

    for registro in _historial(client, user_token, sesion):
        if registro["decision"] == "RECOMMEND":
            assert registro["signal_band"] in ("medium", "strong")
        else:
            assert registro["signal_band"] == "weak"


def test_una_mesa_vacia_no_recomienda_por_falta_de_informacion(
    client: TestClient, user_token: str, sesion: str
) -> None:
    cuerpo = _recomendacion(client, user_token, sesion)
    assert cuerpo["no_bet_reason"] == "insufficient_data"
    assert cuerpo["min_spins_for_signal"] == 10


def test_la_respuesta_trae_el_disclaimer_fijo(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Es la linea que va al pie de la tarjeta (§2.10)."""
    cuerpo = _recomendacion(client, user_token, sesion)
    assert "No es una predicción" in cuerpo["disclaimer"]
    assert "análisis estadístico" in cuerpo["disclaimer"]


def test_el_verde_nunca_aparece_entre_los_candidatos(
    client: TestClient, user_token: str, sesion: str
) -> None:
    for valor in ["0"] * 12:
        _girar(client, user_token, sesion, valor)
    cuerpo = _recomendacion(client, user_token, sesion)
    claves = {c["market"]["key"] for c in cuerpo["candidates"]}
    assert "color:green" not in claves
    assert "tercio:t1+t2" in claves


def test_la_explicacion_trae_teorica_y_observada_por_ventana(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Regla anti-falacia del jugador (§2): en Fase 3 la pareja vive en la
    respuesta y en la seccion desplegable, no en la tarjeta principal."""
    for valor in ["1", "3", "5", "2", "4", "1", "3", "0", "5", "1", "2", "6"]:
        _girar(client, user_token, sesion, valor)

    mejor = _recomendacion(client, user_token, sesion)["best"]
    assert mejor["windows"], "tiene que haber al menos una ventana"
    for ventana in mejor["windows"]:
        assert 0 < ventana["theoretical_probability"] < 1
        assert 0 <= ventana["observed_frequency_shrunk"] <= 1
        assert ventana["observed_ci_low"] <= ventana["observed_ci_high"]
    componentes = mejor["components"]
    assert componentes["weight_deviation"] == pytest.approx(WEIGHT_DEVIATION)
    assert componentes["weight_recency"] == pytest.approx(WEIGHT_RECENCY)


# ---------- Persistencia ----------


def test_cada_giro_deja_una_recomendacion_guardada(
    client: TestClient, user_token: str, sesion: str
) -> None:
    for valor in ["1", "3", "5"]:
        _girar(client, user_token, sesion, valor)

    historial = _historial(client, user_token, sesion)
    assert len(historial) == 3
    assert all(h["decision"] in ("RECOMMEND", "NO_BET") for h in historial)
    # Se guarda tambien el NO APOSTAR, con los datos del mejor candidato: es lo
    # que deja al backtest comparar los giros en que el motor hablo con los que
    # callo.
    assert all(h["market_key"] for h in historial)
    assert all(h["currency"] == "COP" for h in historial)


def test_el_monto_se_guarda_en_centavos(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Dinero en enteros, nunca float."""
    for valor in ["1", "1", "1", "1", "1", "1", "1", "1", "1", "1", "1", "1"]:
        _girar(client, user_token, sesion, valor)

    conmonto = [h for h in _historial(client, user_token, sesion) if h["stake_cents"] is not None]
    assert conmonto, "con un historial tan cargado tuvo que recomendar algo"
    for h in conmonto:
        assert isinstance(h["stake_cents"], int)
        assert h["decision"] == "RECOMMEND"


def test_un_no_apostar_no_guarda_monto(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _girar(client, user_token, sesion, "1")
    for h in _historial(client, user_token, sesion):
        if h["decision"] == "NO_BET":
            assert h["stake_cents"] is None


def test_la_carga_inicial_emite_una_recomendacion(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Al abrir la mesa con numeros ya observados, la tarjeta tiene algo que
    decir antes del primer giro nuevo."""
    r = client.post(
        f"/sessions/{sesion}/spins/bulk",
        json={"values": ["1", "3", "5", "2", "4", "6", "1", "3"],
              "order": "most_recent_last"},
        headers=auth(user_token),
    )
    assert r.status_code == 201, r.text
    assert len(_historial(client, user_token, sesion)) == 1


# ---------- Resolucion ----------


def test_la_recomendacion_se_resuelve_con_el_giro_siguiente(
    client: TestClient, user_token: str, sesion: str
) -> None:
    # Historial muy cargado a rojo para que el motor recomiende algo.
    for valor in ["1", "3", "5"] * 6:
        _girar(client, user_token, sesion, valor)

    antes = _recomendacion(client, user_token, sesion)
    if antes["decision"] != "RECOMMEND":
        pytest.skip("este historial no alcanzo el umbral; el caso lo cubre el motor")

    cubre = set()
    for c in antes["candidates"]:
        if c["market"]["key"] == antes["market"]["key"]:
            cubre = set(c["market"]["group_ids"])
    assert cubre

    _girar(client, user_token, sesion, "1")
    resueltas = [h for h in _historial(client, user_token, sesion) if h["outcome"] != "PENDING"]
    assert resueltas, "el giro siguiente tuvo que cerrar la recomendacion"
    assert resueltas[-1]["outcome"] in ("HIT", "MISS")
    assert resueltas[-1]["resolved_spin_id"] is not None


def test_un_no_apostar_se_queda_pendiente_para_siempre(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """No hubo nada que acertar ni que fallar."""
    _girar(client, user_token, sesion, "1")
    _girar(client, user_token, sesion, "2")

    for h in _historial(client, user_token, sesion):
        if h["decision"] == "NO_BET":
            assert h["outcome"] == "PENDING"
            assert h["resolved_spin_id"] is None


def test_no_apostar_no_avanza_ninguna_progresion(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Regla de §2.10: con NO APOSTAR la progresion no avanza y el saldo no
    cambia. Cobrar un escalon por un giro que el motor pidio no jugar seria
    cobrar por una apuesta que no se hizo."""
    # Historial alterno: ningun mercado se despega, asi que todo es NO APOSTAR.
    for valor in ["1", "2", "3", "4", "5", "6"] * 3:
        _girar(client, user_token, sesion, valor)

    assert all(h["decision"] == "NO_BET" for h in _historial(client, user_token, sesion))
    s = _sesion(client, user_token, sesion)
    assert s["stage_martingale"] == 0
    assert s["stage_two_sector"] == 0
    assert s["bankroll_current"] == 100_000


def test_las_apuestas_reales_no_mueven_las_progresiones(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Una apuesta manual, sin gestion anotada, mueve la banca pero no el
    escalon de ninguna progresion."""
    client.post(
        f"/sessions/{sesion}/bets",
        json={"category": "color", "option_label": "Rojo", "amount": 1_000},
        headers=auth(user_token),
    )
    _girar(client, user_token, sesion, "2")  # negro: la apuesta pierde

    s = _sesion(client, user_token, sesion)
    assert s["bankroll_current"] == 99_000   # la banca si se movio
    assert s["stage_martingale"] == 0        # el escalon no


def _recomendacion_de_un_sector(client, token, sid) -> dict:
    """Historial cargado a rojo hasta que el motor recomiende un mercado de una
    zona, o salta el test si este historial no lo logra."""
    for valor in ["1", "3", "5"] * 6:
        _girar(client, token, sid, valor)
    rec = _recomendacion(client, token, sid)
    if rec["decision"] != "RECOMMEND" or rec["market"]["sectors"] != 1:
        pytest.skip("este historial no dejo una recomendacion de un sector")
    return rec


def _apostar_al_mercado(client, token, sid, rec, strategy: str | None) -> None:
    market = rec["market"]
    r = client.post(
        f"/sessions/{sid}/bets",
        json={
            "category": market["category_id"],
            "option_label": market["group_ids"][0],
            "amount": 1_000,
            "followed_suggestion": True,
            "strategy": strategy,
        },
        headers=auth(token),
    )
    assert r.status_code == 201, r.text
    assert r.json()["strategy"] == strategy


def test_sin_apuesta_ninguna_progresion_avanza(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """El escalon es el de la serie que el usuario lleva de verdad: si no aposto,
    la serie no continuo, aunque la recomendacion haya cerrado en contra."""
    _recomendacion_de_un_sector(client, user_token, sesion)
    antes = _sesion(client, user_token, sesion)

    _girar(client, user_token, sesion, "0")  # el 0 no es de ningun mercado: cierra en contra

    despues = _sesion(client, user_token, sesion)
    assert despues["stage_martingale"] == antes["stage_martingale"]
    assert despues["stage_two_sector"] == antes["stage_two_sector"]
    # La recomendacion se resuelve igual: el backtest mide al motor, no al usuario.
    assert _historial(client, user_token, sesion)[-2]["outcome"] == "MISS"


def test_solo_avanza_la_gestion_con_la_que_se_aposto(
    client: TestClient, user_token: str, sesion: str
) -> None:
    rec = _recomendacion_de_un_sector(client, user_token, sesion)
    antes = _sesion(client, user_token, sesion)

    _apostar_al_mercado(client, user_token, sesion, rec, "martingale")
    _girar(client, user_token, sesion, "0")

    despues = _sesion(client, user_token, sesion)
    assert despues["stage_martingale"] == antes["stage_martingale"] + 1
    assert despues["stage_two_sector"] == antes["stage_two_sector"]


def test_dos_sectores_no_avanza_sobre_un_mercado_de_un_sector(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Aunque la apuesta llegue marcada con esa gestion, sobre un mercado de una
    sola zona la recuperacion de dos sectores no se pudo jugar."""
    rec = _recomendacion_de_un_sector(client, user_token, sesion)
    antes = _sesion(client, user_token, sesion)

    _apostar_al_mercado(client, user_token, sesion, rec, "two_sector_recovery")
    _girar(client, user_token, sesion, "0")

    assert _sesion(client, user_token, sesion)["stage_two_sector"] == antes["stage_two_sector"]


# ---------- Deshacer ----------


def test_deshacer_un_giro_deshace_su_recomendacion(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Si no, corregir un numero mal tecleado dejaria un HIT o un MISS falso en
    el historico, que es justo lo que mide el backtest."""
    for valor in ["1", "3", "5"]:
        _girar(client, user_token, sesion, valor)
    assert len(_historial(client, user_token, sesion)) == 3

    giros = client.get(f"/sessions/{sesion}/spins", headers=auth(user_token)).json()
    r = client.delete(
        f"/sessions/{sesion}/spins/{giros[-1]['id']}", headers=auth(user_token)
    )
    assert r.status_code == 204

    historial = _historial(client, user_token, sesion)
    assert len(historial) == 2
    # La que ese giro habia resuelto vuelve a estar pendiente.
    assert all(h["resolved_spin_id"] != giros[-1]["id"] for h in historial)


def test_deshacer_restaura_los_escalones(
    client: TestClient, user_token: str, sesion: str
) -> None:
    rec = _recomendacion_de_un_sector(client, user_token, sesion)
    antes = _sesion(client, user_token, sesion)

    _apostar_al_mercado(client, user_token, sesion, rec, "martingale")
    _girar(client, user_token, sesion, "0")
    assert _sesion(client, user_token, sesion)["stage_martingale"] == antes["stage_martingale"] + 1
    giros = client.get(f"/sessions/{sesion}/spins", headers=auth(user_token)).json()
    client.delete(f"/sessions/{sesion}/spins/{giros[-1]['id']}", headers=auth(user_token))

    despues = _sesion(client, user_token, sesion)
    assert despues["stage_martingale"] == antes["stage_martingale"]
    assert despues["stage_two_sector"] == antes["stage_two_sector"]


# ---------- Gestion ----------


def test_la_mesa_devuelve_las_tres_progresiones(
    client: TestClient, user_token: str, sesion: str
) -> None:
    for valor in ["1"] * 15:
        _girar(client, user_token, sesion, valor)

    cuerpo = _recomendacion(client, user_token, sesion)
    if cuerpo["decision"] != "RECOMMEND":
        pytest.skip("este historial no alcanzo el umbral")

    assert [s["strategy"] for s in cuerpo["stakes"]] == [
        "flat",
        "martingale",
        "two_sector_recovery",
    ]
    # La recuperacion de dos sectores solo aplica si el mercado cubre dos zonas.
    dos = next(s for s in cuerpo["stakes"] if s["strategy"] == "two_sector_recovery")
    if cuerpo["market"]["sectors"] == 1:
        assert not dos["applicable"]
        assert dos["reason"]
    else:
        assert dos["applicable"]
        assert dos["total_bet"] == dos["bet_per_sector"] * 2


# ---------- Aislamiento ----------


def test_no_se_ve_la_recomendacion_de_una_sesion_ajena(
    client: TestClient, sesion: str
) -> None:
    otro = client.post(
        "/auth/register",
        json={"email": f"otro-{uuid.uuid4().hex[:8]}@ejemplo.com", "password": "clave-segura-123"},
    ).json()["access_token"]
    for ruta in ("recommendation", "recommendation/history"):
        r = client.get(f"/sessions/{sesion}/{ruta}", headers=auth(otro))
        assert r.status_code == 404


def test_requiere_autenticacion(client: TestClient, sesion: str) -> None:
    assert client.get(f"/sessions/{sesion}/recommendation").status_code == 401
