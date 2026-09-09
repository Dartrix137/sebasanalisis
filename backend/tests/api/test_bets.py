"""Apuestas reales y su resolucion automatica al entrar el giro siguiente (§4)."""

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
            "bankroll_start": 100_000,
            "base_bet": 1_000,
            "table_limit": 500_000,
            "strategy": "martingale",
            "strategy_mode": "single",
        },
        headers=auth(user_token),
    ).json()["id"]


def _apostar(client, token, sid, **extra):
    body = {"category": "color", "option_label": "Rojo", "amount": 1_000, **extra}
    return client.post(f"/sessions/{sid}/bets", json=body, headers=auth(token))


def _girar(client, token, sid, valor):
    return client.post(
        f"/sessions/{sid}/spins",
        json={"result_value": valor, "source": "manual"},
        headers=auth(token),
    )


def _sesion(client, token, sid):
    return client.get(f"/sessions/{sid}", headers=auth(token)).json()


# ---------- Registro ----------


def test_registrar_una_apuesta_la_deja_pendiente(
    client: TestClient, user_token: str, sesion: str
) -> None:
    r = _apostar(client, user_token, sesion)
    assert r.status_code == 201
    assert r.json()["status"] == "pending"
    assert r.json()["won"] is None


def test_no_se_puede_apostar_mas_que_la_banca(
    client: TestClient, user_token: str, sesion: str
) -> None:
    r = _apostar(client, user_token, sesion, amount=999_999)
    assert r.status_code == 422


def test_una_opcion_inexistente_es_rechazada(
    client: TestClient, user_token: str, sesion: str
) -> None:
    r = _apostar(client, user_token, sesion, option_label="Morado")
    assert r.status_code == 422


def test_se_pueden_tener_varias_apuestas_pendientes(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """En una mesa real se apuesta a varias cosas en el mismo giro."""
    assert _apostar(client, user_token, sesion).status_code == 201
    assert _apostar(
        client, user_token, sesion, category="tercio", option_label="Bajo"
    ).status_code == 201

    pendientes = [
        b
        for b in client.get(f"/sessions/{sesion}/bets", headers=auth(user_token)).json()
        if b["status"] == "pending"
    ]
    assert len(pendientes) == 2


def test_la_banca_se_valida_por_la_suma_de_lo_comprometido(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Sin esto se podria comprometer mas dinero del que hay en la banca."""
    _apostar(client, user_token, sesion, amount=60_000)
    r = _apostar(client, user_token, sesion, amount=60_000)
    assert r.status_code == 422
    assert "comprometido" in r.json()["detail"]


def test_lo_que_cabe_en_lo_disponible_si_se_acepta(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _apostar(client, user_token, sesion, amount=60_000)
    assert _apostar(client, user_token, sesion, amount=40_000).status_code == 201


# ---------- Varias apuestas: resolucion y avance por el neto del giro ----------


def test_todas_las_pendientes_se_resuelven_contra_el_mismo_giro(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _apostar(client, user_token, sesion)  # Rojo 1.000
    _apostar(client, user_token, sesion, category="tercio", option_label="Bajo")
    giro = _girar(client, user_token, sesion, "1").json()  # rojo y tercio bajo

    apuestas = client.get(f"/sessions/{sesion}/bets", headers=auth(user_token)).json()
    assert all(b["status"] == "resolved" for b in apuestas)
    assert all(b["spin_id"] == giro["id"] for b in apuestas)


def test_ganar_las_dos_suma_los_dos_netos(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _apostar(client, user_token, sesion)  # Rojo, paga 1:1 -> +1.000
    _apostar(client, user_token, sesion, category="tercio", option_label="Bajo")  # 2:1 -> +2.000
    _girar(client, user_token, sesion, "1")
    assert _sesion(client, user_token, sesion)["bankroll_current"] == 103_000


def test_el_giro_cierra_adelante_y_la_progresion_lo_cuenta_como_victoria(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Rojo pierde -1.000, el tercio gana +2.000: el giro cerro en +1.000."""
    _girar(client, user_token, sesion, "2")  # sin apuestas, solo para tener historial
    _apostar(client, user_token, sesion)  # Rojo
    _apostar(client, user_token, sesion, category="tercio", option_label="Bajo")
    _girar(client, user_token, sesion, "2")  # negro, tercio bajo

    s = _sesion(client, user_token, sesion)
    assert s["bankroll_current"] == 101_000
    assert s["strategy_stage"] == 0  # martingala: la serie se cierra


def test_el_giro_cierra_atras_y_la_progresion_avanza(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Rojo pierde -3.000 y el tercio gana +2.000: el giro cerro en -1.000."""
    _apostar(client, user_token, sesion, amount=3_000)  # Rojo
    _apostar(client, user_token, sesion, category="tercio", option_label="Bajo")
    _girar(client, user_token, sesion, "2")

    s = _sesion(client, user_token, sesion)
    assert s["bankroll_current"] == 99_000
    assert s["strategy_stage"] == 1


def test_un_giro_que_cierra_en_cero_no_mueve_el_escalon(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """No hubo nada que recuperar ni nada que cerrar."""
    _apostar(client, user_token, sesion, amount=2_000)  # Rojo, pierde -2.000
    _apostar(client, user_token, sesion, category="tercio", option_label="Bajo", amount=1_000)  # +2.000
    _girar(client, user_token, sesion, "2")

    s = _sesion(client, user_token, sesion)
    assert s["bankroll_current"] == 100_000
    assert s["strategy_stage"] == 0


def test_cerrar_la_sesion_cancela_todas_las_pendientes(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _apostar(client, user_token, sesion)
    _apostar(client, user_token, sesion, category="tercio", option_label="Bajo")
    client.post(f"/sessions/{sesion}/close", headers=auth(user_token))

    apuestas = client.get(f"/sessions/{sesion}/bets", headers=auth(user_token)).json()
    assert all(b["status"] == "cancelled" for b in apuestas)


# ---------- Resolucion automatica ----------


def test_ganar_suma_a_la_banca_y_reinicia_la_progresion(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _apostar(client, user_token, sesion)
    _girar(client, user_token, sesion, "3")  # rojo

    apuesta = client.get(f"/sessions/{sesion}/bets", headers=auth(user_token)).json()[0]
    assert apuesta["status"] == "resolved"
    assert apuesta["won"] is True
    assert apuesta["payout"] == 2_000
    assert apuesta["net_change"] == 1_000

    s = _sesion(client, user_token, sesion)
    assert s["bankroll_current"] == 101_000
    assert s["strategy_stage"] == 0


def test_perder_resta_de_la_banca_y_avanza_la_progresion(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _apostar(client, user_token, sesion)
    _girar(client, user_token, sesion, "2")  # negro

    apuesta = client.get(f"/sessions/{sesion}/bets", headers=auth(user_token)).json()[0]
    assert apuesta["won"] is False
    assert apuesta["payout"] == 0
    assert apuesta["net_change"] == -1_000

    s = _sesion(client, user_token, sesion)
    assert s["bankroll_current"] == 99_000
    assert s["strategy_stage"] == 1  # martingala: siguiente escalon


def test_el_cero_hace_perder_una_apuesta_a_color(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Es exactamente de donde sale la ventaja de la casa."""
    _apostar(client, user_token, sesion)
    _girar(client, user_token, sesion, "0")
    s = _sesion(client, user_token, sesion)
    assert s["bankroll_current"] == 99_000


def test_una_apuesta_de_pago_2a1_devuelve_el_triple(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _apostar(client, user_token, sesion, category="tercio", option_label="Bajo")
    _girar(client, user_token, sesion, "2")
    apuesta = client.get(f"/sessions/{sesion}/bets", headers=auth(user_token)).json()[0]
    assert apuesta["payout"] == 3_000
    assert apuesta["net_change"] == 2_000


def test_la_apuesta_queda_atada_al_giro_que_la_resolvio(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _apostar(client, user_token, sesion)
    giro = _girar(client, user_token, sesion, "3").json()
    apuesta = client.get(f"/sessions/{sesion}/bets", headers=auth(user_token)).json()[0]
    assert apuesta["spin_id"] == giro["id"]


def test_un_giro_sin_apuesta_no_toca_la_banca(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _girar(client, user_token, sesion, "3")
    s = _sesion(client, user_token, sesion)
    assert s["bankroll_current"] == 100_000
    assert s["strategy_stage"] == 0


def test_una_apuesta_ya_resuelta_no_se_vuelve_a_resolver(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _apostar(client, user_token, sesion)
    _girar(client, user_token, sesion, "3")  # gana, banca 101.000
    _girar(client, user_token, sesion, "1")  # sin apuesta nueva
    s = _sesion(client, user_token, sesion)
    assert s["bankroll_current"] == 101_000


def test_varias_rondas_seguidas_acumulan_bien(
    client: TestClient, user_token: str, sesion: str
) -> None:
    for valor, esperado in [("2", 99_000), ("4", 98_000), ("1", 99_000)]:
        _apostar(client, user_token, sesion)
        _girar(client, user_token, sesion, valor)
        assert _sesion(client, user_token, sesion)["bankroll_current"] == esperado


# ---------- Cancelacion y cierre ----------


def test_se_puede_cancelar_una_apuesta_pendiente(
    client: TestClient, user_token: str, sesion: str
) -> None:
    bid = _apostar(client, user_token, sesion).json()["id"]
    r = client.delete(f"/sessions/{sesion}/bets/{bid}", headers=auth(user_token))
    assert r.status_code == 204

    _girar(client, user_token, sesion, "2")
    assert _sesion(client, user_token, sesion)["bankroll_current"] == 100_000


def test_no_se_puede_cancelar_una_apuesta_resuelta(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Cambiaria la banca sobre un hecho que ya ocurrio."""
    bid = _apostar(client, user_token, sesion).json()["id"]
    _girar(client, user_token, sesion, "3")
    r = client.delete(f"/sessions/{sesion}/bets/{bid}", headers=auth(user_token))
    assert r.status_code == 409


def test_cerrar_la_sesion_cancela_la_apuesta_pendiente(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Nunca llego el giro que la resolveria: inventar el resultado seria peor."""
    _apostar(client, user_token, sesion)
    client.post(f"/sessions/{sesion}/close", headers=auth(user_token))
    apuesta = client.get(f"/sessions/{sesion}/bets", headers=auth(user_token)).json()[0]
    assert apuesta["status"] == "cancelled"
    assert apuesta["won"] is None


def test_no_se_puede_apostar_en_sesion_cerrada(
    client: TestClient, user_token: str, sesion: str
) -> None:
    client.post(f"/sessions/{sesion}/close", headers=auth(user_token))
    assert _apostar(client, user_token, sesion).status_code == 409


# ---------- Aislamiento ----------


def test_no_se_ven_ni_se_crean_apuestas_en_sesion_ajena(
    client: TestClient, sesion: str
) -> None:
    otro = client.post(
        "/auth/register",
        json={
            "email": f"otro-{uuid.uuid4().hex[:10]}@ejemplo.com",
            "password": "clave-segura-123",
        },
    ).json()["access_token"]
    assert client.get(f"/sessions/{sesion}/bets", headers=auth(otro)).status_code == 404
    assert _apostar(client, otro, sesion).status_code == 404


def test_las_apuestas_requieren_autenticacion(client: TestClient, sesion: str) -> None:
    assert client.get(f"/sessions/{sesion}/bets").status_code == 401


# ---------- Resumen de cierre (§4) ----------


def test_el_resumen_describe_lo_que_paso(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _apostar(client, user_token, sesion)
    _girar(client, user_token, sesion, "3")  # gana +1.000
    _apostar(client, user_token, sesion, followed_suggestion=True)
    _girar(client, user_token, sesion, "2")  # pierde -1.000

    r = client.get(f"/sessions/{sesion}/summary", headers=auth(user_token))
    assert r.status_code == 200
    c = r.json()
    assert c["total_spins"] == 2
    assert c["total_bets"] == 2
    assert c["win_rate"] == 0.5
    assert c["bankroll_start"] == 100_000
    assert c["bankroll_final"] == 100_000
    assert c["net_change"] == 0
    assert c["followed_suggestion_rate"] == 0.5
    assert c["strategy_used"] == "martingale"


def test_la_caida_maxima_no_la_esconde_un_neto_final_en_cero(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Perder tres veces y recuperar deja neto 0, pero se vivio un -3.000."""
    for valor in ["2", "4", "6"]:  # tres perdidas
        _apostar(client, user_token, sesion)
        _girar(client, user_token, sesion, valor)
    _apostar(client, user_token, sesion, amount=3_000)
    _girar(client, user_token, sesion, "1")  # gana +3.000

    c = client.get(f"/sessions/{sesion}/summary", headers=auth(user_token)).json()
    assert c["net_change"] == 0
    assert c["max_drawdown"] == 3_000


def test_una_sesion_sin_apuestas_da_un_resumen_valido(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _girar(client, user_token, sesion, "3")
    c = client.get(f"/sessions/{sesion}/summary", headers=auth(user_token)).json()
    assert c["total_spins"] == 1
    assert c["total_bets"] == 0
    assert c["win_rate"] == 0.0
    assert c["max_drawdown"] == 0.0


def test_el_resumen_sigue_disponible_con_la_sesion_cerrada(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _apostar(client, user_token, sesion)
    _girar(client, user_token, sesion, "3")
    client.post(f"/sessions/{sesion}/close", headers=auth(user_token))
    c = client.get(f"/sessions/{sesion}/summary", headers=auth(user_token)).json()
    assert c["net_change"] == 1_000


def test_no_se_ve_el_resumen_de_una_sesion_ajena(
    client: TestClient, sesion: str
) -> None:
    otro = client.post(
        "/auth/register",
        json={
            "email": f"otro-{uuid.uuid4().hex[:10]}@ejemplo.com",
            "password": "clave-segura-123",
        },
    ).json()["access_token"]
    assert client.get(f"/sessions/{sesion}/summary", headers=auth(otro)).status_code == 404


# ---------- Deshacer un giro que ya resolvio apuestas ----------


def test_deshacer_el_giro_devuelve_la_banca_y_el_escalon(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """El numero mal tecleado se deshace; su efecto sobre el dinero, tambien."""
    _apostar(client, user_token, sesion)
    _girar(client, user_token, sesion, "2")  # negro: la apuesta al Rojo pierde

    antes = _sesion(client, user_token, sesion)
    assert antes["bankroll_current"] == 99_000
    assert antes["strategy_stage"] == 1

    giros = client.get(f"/sessions/{sesion}/spins", headers=auth(user_token)).json()
    r = client.delete(
        f"/sessions/{sesion}/spins/{giros[-1]['id']}", headers=auth(user_token)
    )
    assert r.status_code == 204

    despues = _sesion(client, user_token, sesion)
    assert despues["bankroll_current"] == 100_000
    assert despues["strategy_stage"] == 0


def test_al_deshacer_la_apuesta_vuelve_a_estar_pendiente(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """La apuesta se hizo de verdad: lo que se deshace es el numero, no ella."""
    _apostar(client, user_token, sesion)
    _girar(client, user_token, sesion, "2")
    giros = client.get(f"/sessions/{sesion}/spins", headers=auth(user_token)).json()
    client.delete(f"/sessions/{sesion}/spins/{giros[-1]['id']}", headers=auth(user_token))

    apuesta = client.get(f"/sessions/{sesion}/bets", headers=auth(user_token)).json()[0]
    assert apuesta["status"] == "pending"
    assert apuesta["spin_id"] is None
    assert apuesta["won"] is None
    assert apuesta["net_change"] is None


def test_tras_deshacer_el_giro_correcto_resuelve_la_misma_apuesta(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Corregir el numero deja la sesion como si nunca se hubiera equivocado."""
    _apostar(client, user_token, sesion)
    _girar(client, user_token, sesion, "2")  # tecleado por error
    giros = client.get(f"/sessions/{sesion}/spins", headers=auth(user_token)).json()
    client.delete(f"/sessions/{sesion}/spins/{giros[-1]['id']}", headers=auth(user_token))

    _girar(client, user_token, sesion, "3")  # el que habia salido de verdad: rojo

    s = _sesion(client, user_token, sesion)
    assert s["bankroll_current"] == 101_000
    assert s["strategy_stage"] == 0
    apuesta = client.get(f"/sessions/{sesion}/bets", headers=auth(user_token)).json()[0]
    assert apuesta["won"] is True


def test_deshacer_revierte_todas_las_apuestas_del_giro(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _apostar(client, user_token, sesion)
    _apostar(client, user_token, sesion, category="tercio", option_label="Bajo")
    _girar(client, user_token, sesion, "1")  # las dos ganan

    giros = client.get(f"/sessions/{sesion}/spins", headers=auth(user_token)).json()
    client.delete(f"/sessions/{sesion}/spins/{giros[-1]['id']}", headers=auth(user_token))

    apuestas = client.get(f"/sessions/{sesion}/bets", headers=auth(user_token)).json()
    assert all(b["status"] == "pending" for b in apuestas)
    assert _sesion(client, user_token, sesion)["bankroll_current"] == 100_000


def test_deshacer_un_giro_sin_apuestas_no_toca_nada(
    client: TestClient, user_token: str, sesion: str
) -> None:
    _girar(client, user_token, sesion, "3")
    giros = client.get(f"/sessions/{sesion}/spins", headers=auth(user_token)).json()
    client.delete(f"/sessions/{sesion}/spins/{giros[-1]['id']}", headers=auth(user_token))

    s = _sesion(client, user_token, sesion)
    assert s["bankroll_current"] == 100_000
    assert s["strategy_stage"] == 0


def test_se_puede_deshacer_hasta_dejar_la_mesa_vacia(
    client: TestClient, user_token: str, sesion: str
) -> None:
    """Una sesion sin giros es un estado valido: es como empieza."""
    for valor in ["1", "2", "3"]:
        _girar(client, user_token, sesion, valor)

    for _ in range(3):
        giros = client.get(f"/sessions/{sesion}/spins", headers=auth(user_token)).json()
        r = client.delete(
            f"/sessions/{sesion}/spins/{giros[-1]['id']}", headers=auth(user_token)
        )
        assert r.status_code == 204

    assert client.get(f"/sessions/{sesion}/spins", headers=auth(user_token)).json() == []
    # Y el analisis sigue respondiendo, con las probabilidades teoricas.
    panel = client.get(
        f"/sessions/{sesion}/suggestions/latest", headers=auth(user_token)
    ).json()
    assert len(panel["top"]) > 0
