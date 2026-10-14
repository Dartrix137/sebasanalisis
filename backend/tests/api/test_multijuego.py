"""Plataforma multijuego (docs/PLATAFORMA_COMPLETA.md §7).

Los tests de aceptacion de §7.6 que son del backend, mas los de la regla n.º 7
de `has_access` (juego incluido en el plan), el estado de un juego y la
seleccion de juegos por plan en el admin.

El fixture de dados (`tests/fixtures/dados_d6.json`) es solo eso: un fixture.
No se siembra ni se publica (§7.5). Es un dado de seis caras y no la suma de
dos: el motor supone resultados equiprobables, y las sumas de dos dados no lo
son.
"""

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.game_config_validation import (
    check_payouts_against_house_edge,
    validate_game_config,
)
from app.schemas.games import GameVariantConfig
from tests.api.conftest import auth, game_body, register_raw

DADOS = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "dados_d6.json").read_text(encoding="utf-8")
)
DADOS_HOUSE_EDGE = 0.05
MOTIVO = "Prueba de la plataforma multijuego"
PASSWORD = "clave-segura-123"


# ---------- Ayudas ----------


def _crear_juego(client: TestClient, admin_token: str, **cambios) -> dict:
    sufijo = uuid.uuid4().hex[:8]
    r = client.post(
        "/admin/games", json=game_body("Dados", "dice", sufijo, **cambios), headers=auth(admin_token)
    )
    assert r.status_code == 201, r.text
    return r.json()


def _crear_variante(client: TestClient, admin_token: str, game_id: str) -> dict:
    r = client.post(
        f"/admin/games/{game_id}/variants",
        json={
            "name": "d6",
            "description": "Un dado de seis caras.",
            "house_edge": DADOS_HOUSE_EDGE,
            "config": DADOS,
        },
        headers=auth(admin_token),
    )
    assert r.status_code == 201, r.text
    return r.json()


def _juego_con_variante(client: TestClient, admin_token: str, **cambios) -> tuple[dict, dict]:
    juego = _crear_juego(client, admin_token, **cambios)
    return juego, _crear_variante(client, admin_token, juego["id"])


def _abrir_mesa(client: TestClient, token: str, variant_id: str):
    return client.post(
        "/sessions",
        json={
            "game_variant_id": variant_id,
            "bankroll_start": 100_000,
            "base_bet": 1_000,
            "table_limit": 500_000,
        },
        headers=auth(token),
    )


def _menu(client: TestClient, token: str) -> dict[str, dict]:
    r = client.get("/games", params={"limit": 100}, headers=auth(token))
    assert r.status_code == 200, r.text
    return {g["id"]: g for g in r.json()["items"]}


def _crear_plan(client: TestClient, admin_token: str) -> dict:
    r = client.post(
        "/admin/plans",
        json={
            "code": f"p{uuid.uuid4().hex[:10]}",
            "name": "Plan de prueba",
            "description": "Plan de prueba",
            "price_cents": 5_000_000,
            "currency": "COP",
            "interval": "month",
            "reason": MOTIVO,
        },
        headers=auth(admin_token),
    )
    assert r.status_code == 201, r.text
    return r.json()


def _juegos_del_plan(client: TestClient, admin_token: str, plan_id: str, game_ids: list[str]):
    return client.put(
        f"/admin/plans/{plan_id}/games",
        json={"game_ids": game_ids, "reason": MOTIVO},
        headers=auth(admin_token),
    )


def _suscriptor(client: TestClient, db, plan_id: str) -> str:
    """Una cuenta sin acceso manual, con una suscripcion vigente al plan."""
    registro = register_raw(client, f"multi-{uuid.uuid4().hex[:12]}@ejemplo.com", PASSWORD)
    db.execute(
        text(
            "INSERT INTO subscriptions "
            "(id, user_id, plan_id, provider, status, price_cents, currency, current_period_end) "
            "SELECT :id, :u, p.id, 'wompi', 'active', p.price_cents, p.currency, :e "
            "FROM plans p WHERE p.id = :p"
        ),
        {
            "id": str(uuid.uuid4()),
            "u": registro["user"]["id"],
            "p": plan_id,
            "e": datetime.now(UTC) + timedelta(days=10),
        },
    )
    db.commit()
    return registro["access_token"]


def _bitacora(db, target_id: str) -> list:
    return list(
        db.execute(
            text(
                "SELECT action, before, after, reason FROM admin_audit_log "
                "WHERE target_id = :t ORDER BY created_at"
            ),
            {"t": target_id},
        )
    )


# ---------- §7.5: fixture de dados de punta a punta ----------


def test_el_fixture_de_dados_es_una_configuracion_valida() -> None:
    """Pasa por el validador de la skill `categories-json-validator` sin errores
    ni avisos: cada categoria cubre los seis resultados y todos los pagos dan la
    misma ventaja de la casa."""
    config = GameVariantConfig.model_validate(DADOS)
    result = validate_game_config(config)
    assert result.errors == [] and result.warnings == []
    assert check_payouts_against_house_edge(config, DADOS_HOUSE_EDGE) == []


def test_dados_de_punta_a_punta_sin_tocar_el_motor(
    client: TestClient, admin_token: str, user_token: str
) -> None:
    """§7.5: se crea por la API de admin, se abre una mesa, se cargan giros y se
    pide la recomendacion. Si esto falla, se colo logica de ruleta fuera de los
    datos."""
    juego, variante = _juego_con_variante(client, admin_token)
    assert variante["config"]["display"]["columns"] == 6

    # Aparece en el menu y se puede jugar.
    menu = _menu(client, user_token)
    assert juego["id"] in menu
    assert menu[juego["id"]]["access"] == {"granted": True, "reason": "invited"}
    assert [v["name"] for v in menu[juego["id"]]["variants"]] == ["d6"]

    r = _abrir_mesa(client, user_token, variante["id"])
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    # Carga inicial con un sesgo fuerte a los pares, del mas antiguo al mas reciente.
    r = client.post(
        f"/sessions/{sid}/spins/bulk",
        json={"values": ["2", "4", "6"] * 12, "order": "most_recent_last"},
        headers=auth(user_token),
    )
    assert r.status_code == 201, r.text

    # Un valor que no es del dado se rechaza, no se descarta en silencio.
    r = client.post(
        f"/sessions/{sid}/spins",
        json={"result_value": "7", "source": "manual"},
        headers=auth(user_token),
    )
    assert r.status_code == 422

    r = client.get(f"/sessions/{sid}/recommendation", headers=auth(user_token))
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["decision"] == "RECOMMEND"
    assert rec["market"]["category_id"] in {"parity", "high_low", "third"}
    categorias = {c["id"]: c for c in DADOS["categories"]}
    grupos = categorias[rec["market"]["category_id"]]["groups"]
    assert set(rec["market"]["group_ids"]) <= set(grupos)

    # El giro siguiente resuelve la recomendacion, como en la ruleta.
    r = client.post(
        f"/sessions/{sid}/spins",
        json={"result_value": "4", "source": "manual"},
        headers=auth(user_token),
    )
    assert r.status_code == 201, r.text
    historial = client.get(
        f"/sessions/{sid}/recommendation/history", headers=auth(user_token)
    ).json()
    assert any(h["outcome"] in {"HIT", "MISS"} for h in historial)

    for ruta in ("suggestions/latest", "streak", "performance", "summary"):
        assert client.get(f"/sessions/{sid}/{ruta}", headers=auth(user_token)).status_code == 200


# ---------- §7.3: registro de modulos ----------


def test_un_modulo_reservado_o_desconocido_se_rechaza_al_crear(
    client: TestClient, admin_token: str
) -> None:
    sufijo = uuid.uuid4().hex[:8]
    r = client.post(
        "/admin/games",
        json=game_body("Futbol", "sports", sufijo, module="sports"),
        headers=auth(admin_token),
    )
    assert r.status_code == 422
    assert "reservado" in r.json()["detail"]

    r = client.post(
        "/admin/games",
        json=game_body("Otro", "otro", sufijo, module="cartas_magicas"),
        headers=auth(admin_token),
    )
    assert r.status_code == 422


def test_todo_router_de_juego_esta_en_el_registro() -> None:
    """Los routers de la mesa salen del registro de modulos, no de una lista
    aparte en `main.py`."""
    from app.api.game_modules import MODULES, game_routers
    from app.models.game import GAME_MODULES

    assert set(MODULES) == set(GAME_MODULES)
    assert MODULES["sports"] is None
    prefijos = {r.prefix for r in game_routers()}
    assert prefijos == {"/sessions", ""}


# ---------- §7.2: metadatos y estado ----------


def test_slug_invalido_o_repetido_se_rechaza(client: TestClient, admin_token: str) -> None:
    sufijo = uuid.uuid4().hex[:8]
    r = client.post(
        "/admin/games",
        json=game_body("X", "x", sufijo, slug="Con Espacios"),
        headers=auth(admin_token),
    )
    assert r.status_code == 422

    juego = _crear_juego(client, admin_token)
    r = client.post(
        "/admin/games",
        json=game_body("Y", "y", uuid.uuid4().hex[:8], slug=juego["slug"]),
        headers=auth(admin_token),
    )
    assert r.status_code == 409


def test_el_slug_no_se_edita(client: TestClient, admin_token: str) -> None:
    juego = _crear_juego(client, admin_token)
    r = client.patch(
        f"/admin/games/{juego['id']}", json={"slug": "otro-slug"}, headers=auth(admin_token)
    )
    assert r.status_code == 409  # no hay nada que cambiar: el slug no es editable
    assert client.get("/admin/games", headers=auth(admin_token)).status_code == 200


def test_un_juego_nuevo_nace_oculto_y_crearlo_deja_fila(
    client: TestClient, admin_token: str, db
) -> None:
    body = game_body("Dados", "dice", uuid.uuid4().hex[:8])
    del body["status"]
    r = client.post("/admin/games", json=body, headers=auth(admin_token))
    assert r.status_code == 201
    assert r.json()["status"] == "hidden"
    filas = _bitacora(db, r.json()["id"])
    assert [(f.action, f.reason) for f in filas] == [("game.create", "Juego de prueba")]

    sin_motivo = {k: v for k, v in body.items() if k != "reason"}
    sin_motivo.update(type=f"t_{uuid.uuid4().hex[:8]}", slug=f"s-{uuid.uuid4().hex[:8]}")
    assert client.post("/admin/games", json=sin_motivo, headers=auth(admin_token)).status_code == 422


def test_cambiar_el_estado_pide_motivo_y_deja_fila(
    client: TestClient, admin_token: str, db
) -> None:
    juego = _crear_juego(client, admin_token)
    r = client.patch(
        f"/admin/games/{juego['id']}", json={"status": "hidden"}, headers=auth(admin_token)
    )
    assert r.status_code == 422
    assert [f.action for f in _bitacora(db, juego["id"])] == ["game.create"]

    r = client.patch(
        f"/admin/games/{juego['id']}",
        json={"status": "coming_soon", "reason": MOTIVO},
        headers=auth(admin_token),
    )
    assert r.status_code == 200
    filas = _bitacora(db, juego["id"])
    assert (filas[-1].action, filas[-1].before, filas[-1].after, filas[-1].reason) == (
        "game.status.update",
        {"status": "active"},
        {"status": "coming_soon"},
        MOTIVO,
    )

    # Editar la presentacion no pide motivo ni deja fila.
    r = client.patch(
        f"/admin/games/{juego['id']}",
        json={"description": "Otra descripcion", "icon": "dados", "sort_order": 5},
        headers=auth(admin_token),
    )
    assert r.status_code == 200
    assert len(_bitacora(db, juego["id"])) == 2


def test_menu_segun_el_estado_del_juego(
    client: TestClient, admin_token: str, user_token: str
) -> None:
    activo, v_activo = _juego_con_variante(client, admin_token)
    oculto, v_oculto = _juego_con_variante(client, admin_token, status="hidden")
    pronto, v_pronto = _juego_con_variante(client, admin_token, status="coming_soon")

    menu = _menu(client, user_token)
    assert activo["id"] in menu and pronto["id"] in menu
    assert oculto["id"] not in menu
    assert menu[pronto["id"]]["status"] == "coming_soon"

    # El administrador ve tambien los ocultos.
    assert oculto["id"] in _menu(client, admin_token)

    # Un cliente no abre mesa en un juego oculto (no existe para el) ni en uno
    # "proximamente"; un administrador abre en los dos, para probarlos.
    assert _abrir_mesa(client, user_token, v_oculto["id"]).status_code == 404
    assert _abrir_mesa(client, user_token, v_pronto["id"]).status_code == 409
    assert _abrir_mesa(client, admin_token, v_oculto["id"]).status_code == 201
    assert _abrir_mesa(client, admin_token, v_pronto["id"]).status_code == 201
    assert _abrir_mesa(client, user_token, v_activo["id"]).status_code == 201

    r = client.get(f"/games/{oculto['id']}/variants", headers=auth(user_token))
    assert r.status_code == 404


def test_una_mesa_abierta_sigue_funcionando_si_su_juego_se_oculta(
    client: TestClient, admin_token: str, user_token: str
) -> None:
    juego, variante = _juego_con_variante(client, admin_token)
    sid = _abrir_mesa(client, user_token, variante["id"]).json()["id"]
    client.patch(
        f"/admin/games/{juego['id']}",
        json={"status": "hidden", "reason": MOTIVO},
        headers=auth(admin_token),
    )
    r = client.post(
        f"/sessions/{sid}/spins",
        json={"result_value": "3", "source": "manual"},
        headers=auth(user_token),
    )
    assert r.status_code == 201, r.text
    assert client.get(f"/sessions/{sid}/recommendation", headers=auth(user_token)).status_code == 200


def test_lista_del_admin_pagina_y_filtra(client: TestClient, admin_token: str) -> None:
    oculto = _crear_juego(client, admin_token, status="hidden")
    r = client.get(
        "/admin/games", params={"status": "hidden", "limit": 100}, headers=auth(admin_token)
    )
    assert r.status_code == 200
    body = r.json()
    assert {g["status"] for g in body["items"]} == {"hidden"}
    assert oculto["id"] in {g["id"] for g in body["items"]}

    r = client.get(
        "/admin/games", params={"q": oculto["slug"]}, headers=auth(admin_token)
    ).json()
    assert [g["id"] for g in r["items"]] == [oculto["id"]] and r["total"] == 1

    r = client.get("/admin/games", params={"limit": 1}, headers=auth(admin_token)).json()
    assert len(r["items"]) == 1 and r["total"] > 1
    assert client.get("/admin/games", params={"limit": 101}, headers=auth(admin_token)).status_code == 422


def test_la_lista_del_admin_es_solo_para_administradores(
    client: TestClient, user_token: str
) -> None:
    assert client.get("/admin/games", headers=auth(user_token)).status_code == 403


# ---------- Pista de presentacion `display` ----------


@pytest.mark.parametrize(
    "display",
    [
        {"outcome_tone_category": "no_existe"},
        {"outcome_tone_category": "parity", "tones": {"no_existe": "red"}},
        {"tones": {"even": "red"}},
        {"outcome_tone_category": "parity", "tones": {"even": "morado"}},
        {"columns": 0},
    ],
)
def test_una_pista_de_presentacion_mal_formada_se_rechaza(
    client: TestClient, admin_token: str, display: dict
) -> None:
    juego = _crear_juego(client, admin_token)
    r = client.post(
        f"/admin/games/{juego['id']}/variants",
        json={"name": "d6", "house_edge": DADOS_HOUSE_EDGE, "config": {**DADOS, "display": display}},
        headers=auth(admin_token),
    )
    assert r.status_code == 422, r.text


def test_la_pista_es_opcional(client: TestClient, admin_token: str) -> None:
    juego = _crear_juego(client, admin_token)
    sin_pista = {k: v for k, v in DADOS.items() if k != "display"}
    r = client.post(
        f"/admin/games/{juego['id']}/variants",
        json={"name": "d6", "house_edge": DADOS_HOUSE_EDGE, "config": sin_pista},
        headers=auth(admin_token),
    )
    assert r.status_code == 201
    assert r.json()["config"]["display"] is None


def test_la_ruleta_sembrada_trae_su_pista() -> None:
    from app.db.seed import ROULETTE_VARIANTS, load_config

    for _, _, _, archivo in ROULETTE_VARIANTS:
        config = load_config(archivo)
        assert config.display is not None
        assert config.display.outcome_tone_category == "color"
        assert validate_game_config(config).errors == []


# ---------- §7.4: acceso por juego (regla n.º 7) ----------


def test_un_plan_sin_juegos_incluye_todos_tambien_los_nuevos(
    client: TestClient, admin_token: str, db
) -> None:
    plan = _crear_plan(client, admin_token)
    assert plan["all_games"] is True and plan["game_ids"] == []
    token = _suscriptor(client, db, plan["id"])

    # Un juego creado despues de suscribirse tambien esta incluido.
    _, variante = _juego_con_variante(client, admin_token)
    assert _abrir_mesa(client, token, variante["id"]).status_code == 201


def test_un_juego_fuera_del_plan_da_403_game_not_in_plan(
    client: TestClient, admin_token: str, db
) -> None:
    incluido, v_incluido = _juego_con_variante(client, admin_token)
    excluido, v_excluido = _juego_con_variante(client, admin_token)
    plan = _crear_plan(client, admin_token)
    assert _juegos_del_plan(client, admin_token, plan["id"], [incluido["id"]]).status_code == 200
    token = _suscriptor(client, db, plan["id"])

    r = _abrir_mesa(client, token, v_excluido["id"])
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "game_not_in_plan"
    assert _abrir_mesa(client, token, v_incluido["id"]).status_code == 201

    # El menu lo muestra igual, marcado, para ofrecerlo en otro plan.
    menu = _menu(client, token)
    assert menu[excluido["id"]]["access"] == {"granted": False, "reason": "game_not_in_plan"}
    assert menu[incluido["id"]]["access"] == {"granted": True, "reason": "subscription"}

    # La cuenta tiene acceso: la decision sin juego no cambia.
    me = client.get("/auth/me", headers=auth(token)).json()
    assert me["access"]["reason"] == "subscription"


def test_el_acceso_manual_y_el_administrador_incluyen_todos_los_juegos(
    client: TestClient, admin_token: str, user_token: str, db
) -> None:
    """`user_token` es una cuenta `invited`; se le pone ademas una suscripcion a
    un plan que no incluye el juego, y el acceso manual pasa por encima."""
    juego, variante = _juego_con_variante(client, admin_token)
    otro = _crear_juego(client, admin_token)
    plan = _crear_plan(client, admin_token)
    _juegos_del_plan(client, admin_token, plan["id"], [otro["id"]])

    user_id = client.get("/auth/me", headers=auth(user_token)).json()["id"]
    db.execute(
        text(
            "INSERT INTO subscriptions "
            "(id, user_id, plan_id, provider, status, price_cents, currency, current_period_end) "
            "VALUES (:id, :u, :p, 'wompi', 'active', 100, 'COP', :e)"
        ),
        {"id": str(uuid.uuid4()), "u": user_id, "p": plan["id"], "e": datetime.now(UTC) + timedelta(days=5)},
    )
    db.commit()
    assert _abrir_mesa(client, user_token, variante["id"]).status_code == 201
    assert _abrir_mesa(client, admin_token, variante["id"]).status_code == 201

    db.execute(text("UPDATE users SET access_type = 'full' WHERE id = :u"), {"u": user_id})
    db.commit()
    assert _abrir_mesa(client, user_token, variante["id"]).status_code == 201


def test_todas_las_rutas_de_una_mesa_aplican_el_juego_incluido_en_el_plan(
    client: TestClient, admin_token: str, db
) -> None:
    """Como el test que recorre los routers con una cuenta sin acceso, pero con
    una mesa real cuyo juego el plan deja de incluir: toda ruta sobre esa mesa
    responde `403 game_not_in_plan`, antes incluso de validar el cuerpo. Un
    endpoint nuevo sobre una mesa no puede olvidarlo."""
    from app.main import app

    juego, variante = _juego_con_variante(client, admin_token)
    otro = _crear_juego(client, admin_token)
    plan = _crear_plan(client, admin_token)
    token = _suscriptor(client, db, plan["id"])
    sid = _abrir_mesa(client, token, variante["id"]).json()["id"]

    # El plan pasa a incluir solo otro juego. Con una suscripcion vigente el
    # admin no puede quitarlo, asi que se cambia por debajo, como si la cuenta
    # se hubiera suscrito despues del cambio.
    db.execute(
        text("INSERT INTO plan_games (plan_id, game_id) VALUES (:p, :g)"),
        {"p": plan["id"], "g": otro["id"]},
    )
    db.commit()

    probadas = 0
    for ruta, operaciones in app.openapi()["paths"].items():
        if "{session_id}" not in ruta:
            continue
        path = ruta.replace("{session_id}", sid)
        path = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
        for method in operaciones:
            r = client.request(method.upper(), path, headers=auth(token))
            assert r.status_code == 403, f"{method} {ruta} respondió {r.status_code}"
            assert r.json()["detail"]["code"] == "game_not_in_plan", f"{method} {ruta}"
            probadas += 1
    assert probadas >= 20

    # Y la lista de mesas no se cierra: la cuenta sigue teniendo acceso.
    assert client.get("/sessions", headers=auth(token)).status_code == 200


# ---------- §4.4: juegos por plan en el admin ----------


def test_elegir_los_juegos_de_un_plan_deja_fila_con_motivo(
    client: TestClient, admin_token: str, db
) -> None:
    juego = _crear_juego(client, admin_token)
    plan = _crear_plan(client, admin_token)

    r = client.put(
        f"/admin/plans/{plan['id']}/games",
        json={"game_ids": [juego["id"]]},
        headers=auth(admin_token),
    )
    assert r.status_code == 422  # sin motivo

    r = _juegos_del_plan(client, admin_token, plan["id"], [juego["id"]])
    assert r.status_code == 200, r.text
    assert (r.json()["all_games"], r.json()["game_ids"]) == (False, [juego["id"]])
    filas = _bitacora(db, plan["id"])
    assert (filas[-1].action, filas[-1].before, filas[-1].after, filas[-1].reason) == (
        "plan.games.update",
        {"all_games": True, "games": []},
        {"all_games": False, "games": [juego["slug"]]},
        MOTIVO,
    )

    # Lo mismo otra vez no cambia nada.
    assert _juegos_del_plan(client, admin_token, plan["id"], [juego["id"]]).status_code == 409
    # Un juego que no existe.
    r = _juegos_del_plan(client, admin_token, plan["id"], [str(uuid.uuid4())])
    assert r.status_code == 422
    # Volver a "todos".
    r = _juegos_del_plan(client, admin_token, plan["id"], [])
    assert r.status_code == 200 and r.json()["all_games"] is True


def test_no_se_le_quita_un_juego_a_un_plan_con_suscripciones_vigentes(
    client: TestClient, admin_token: str, db
) -> None:
    a = _crear_juego(client, admin_token)
    b = _crear_juego(client, admin_token)
    plan = _crear_plan(client, admin_token)
    _juegos_del_plan(client, admin_token, plan["id"], [a["id"]])
    _suscriptor(client, db, plan["id"])
    antes = len(_bitacora(db, plan["id"]))

    # Agregar si se puede.
    assert _juegos_del_plan(client, admin_token, plan["id"], [a["id"], b["id"]]).status_code == 200
    # Quitar no.
    r = _juegos_del_plan(client, admin_token, plan["id"], [b["id"]])
    assert r.status_code == 409
    assert a["name"] in r.json()["detail"]
    assert len(_bitacora(db, plan["id"])) == antes + 1
    # Pasar a "todos" no quita nada: se puede.
    assert _juegos_del_plan(client, admin_token, plan["id"], []).status_code == 200


def test_de_todos_a_una_lista_con_suscripciones_vigentes(
    client: TestClient, admin_token: str, db
) -> None:
    """Un plan sin filas incluye todos los juegos que existen: pasar a una
    lista que deje alguno fuera es quitarlo."""
    a = _crear_juego(client, admin_token)
    plan = _crear_plan(client, admin_token)
    _suscriptor(client, db, plan["id"])
    assert _juegos_del_plan(client, admin_token, plan["id"], [a["id"]]).status_code == 409


def test_juegos_por_plan_solo_para_administradores(
    client: TestClient, admin_token: str, user_token: str
) -> None:
    plan = _crear_plan(client, admin_token)
    r = client.put(
        f"/admin/plans/{plan['id']}/games",
        json={"game_ids": [], "reason": MOTIVO},
        headers=auth(user_token),
    )
    assert r.status_code == 403


def test_los_planes_publicos_dicen_que_juegos_incluyen(
    client: TestClient, admin_token: str, user_token: str
) -> None:
    visible = _crear_juego(client, admin_token)
    oculto = _crear_juego(client, admin_token, status="hidden")
    plan = _crear_plan(client, admin_token)
    _juegos_del_plan(client, admin_token, plan["id"], [visible["id"], oculto["id"]])

    planes = {p["id"]: p for p in client.get("/plans", headers=auth(user_token)).json()}
    publico = planes[plan["id"]]
    assert publico["all_games"] is False
    # El juego oculto no se nombra a los clientes.
    assert [g["id"] for g in publico["games"]] == [visible["id"]]


# ---------- Entrega 2: la mesa sabe de que juego es ----------


def test_la_sesion_trae_el_slug_y_el_modulo_de_su_juego(
    client: TestClient, admin_token: str, user_token: str
) -> None:
    """El frontend arma la URL de la mesa (`/juegos/<slug>/mesa/<id>`) y elige
    su pantalla con estos dos campos."""
    juego, variante = _juego_con_variante(client, admin_token)
    sid = _abrir_mesa(client, user_token, variante["id"]).json()["id"]

    sesion = client.get(f"/sessions/{sid}", headers=auth(user_token)).json()
    assert (sesion["game_slug"], sesion["game_module"]) == (juego["slug"], "discrete_outcome")
    lista = client.get("/sessions", headers=auth(user_token)).json()
    assert next(s for s in lista if s["id"] == sid)["game_slug"] == juego["slug"]
