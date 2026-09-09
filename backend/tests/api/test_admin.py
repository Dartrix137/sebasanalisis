"""Tests de integracion del panel de administracion (paso 3)."""

import uuid

from fastapi.testclient import TestClient

from tests.api.conftest import auth

DADOS_CONFIG = {
    "possible_outcomes": [str(n) for n in range(2, 13)],
    "categories": [
        {
            "id": "parity",
            "label": "Par/Impar",
            "shrinkage_alpha": 8,
            "groups": {
                "even": {"label": "Par", "outcomes": ["2", "4", "6", "8", "10", "12"], "payout": 1},
                "odd": {"label": "Impar", "outcomes": ["3", "5", "7", "9", "11"], "payout": 1},
            },
        }
    ],
}


def _game_body() -> dict:
    sufijo = uuid.uuid4().hex[:8]
    return {"name": f"Dados {sufijo}", "type": f"dice_{sufijo}", "active": True}


def _crear_juego(client: TestClient, token: str) -> str:
    return client.post("/admin/games", json=_game_body(), headers=auth(token)).json()["id"]


# ---------- Autorizacion ----------


def test_endpoints_de_admin_rechazan_usuario_normal(client: TestClient, user_token: str) -> None:
    assert client.get("/admin/users", headers=auth(user_token)).status_code == 403
    r = client.post("/admin/games", json=_game_body(), headers=auth(user_token))
    assert r.status_code == 403


def test_endpoints_de_admin_rechazan_sin_token(client: TestClient) -> None:
    assert client.get("/admin/users").status_code == 401
    assert client.post("/admin/games", json=_game_body()).status_code == 401


# ---------- CRUD de juegos ----------


def test_crear_y_editar_juego(client: TestClient, admin_token: str) -> None:
    body = _game_body()
    r = client.post("/admin/games", json=body, headers=auth(admin_token))
    assert r.status_code == 201, r.text
    game = r.json()
    assert game["type"] == body["type"]
    assert game["variants"] == []

    r = client.patch(
        f"/admin/games/{game['id']}",
        json={"name": "Renombrado", "active": False},
        headers=auth(admin_token),
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Renombrado"
    assert r.json()["active"] is False


def test_tipo_de_juego_duplicado_es_rechazado(client: TestClient, admin_token: str) -> None:
    body = _game_body()
    assert client.post("/admin/games", json=body, headers=auth(admin_token)).status_code == 201
    assert client.post("/admin/games", json=body, headers=auth(admin_token)).status_code == 409


def test_juego_inexistente_da_404(client: TestClient, admin_token: str) -> None:
    r = client.patch(f"/admin/games/{uuid.uuid4()}", json={"name": "x"}, headers=auth(admin_token))
    assert r.status_code == 404


# ---------- CRUD de variantes ----------


def test_crear_variante_con_config_valida(client: TestClient, admin_token: str) -> None:
    game_id = _crear_juego(client, admin_token)
    r = client.post(
        f"/admin/games/{game_id}/variants",
        json={"name": "two_d6", "house_edge": 0.05, "config": DADOS_CONFIG, "active": True},
        headers=auth(admin_token),
    )
    assert r.status_code == 201, r.text
    variant = r.json()
    # El alias config <-> categories_json debe poblar la respuesta desde el ORM.
    assert len(variant["config"]["possible_outcomes"]) == 11
    assert variant["config"]["categories"][0]["groups"]["even"]["label"] == "Par"
    assert variant["config"]["categories"][0]["shrinkage_alpha"] == 8


def test_variante_con_outcome_fuera_de_possible_outcomes_es_rechazada(
    client: TestClient, admin_token: str
) -> None:
    """Regla 3 del validador: bloqueante, no un aviso."""
    game_id = _crear_juego(client, admin_token)
    config = {
        "possible_outcomes": ["1", "2", "3"],
        "categories": [
            {"id": "x", "label": "X", "groups": {"a": {"outcomes": ["1", "99"], "payout": 1}}}
        ],
    }
    r = client.post(
        f"/admin/games/{game_id}/variants",
        json={"name": "mala", "house_edge": 0.05, "config": config},
        headers=auth(admin_token),
    )
    assert r.status_code == 422
    assert "99" in r.text


def test_variante_con_grupos_solapados_es_rechazada(client: TestClient, admin_token: str) -> None:
    """Dos grupos de la misma categoria compartiendo un resultado harian que las
    probabilidades de esa categoria sumen mas de 1."""
    game_id = _crear_juego(client, admin_token)
    config = {
        "possible_outcomes": ["1", "2", "3"],
        "categories": [
            {
                "id": "x",
                "label": "X",
                "groups": {
                    "a": {"outcomes": ["1", "2"], "payout": 1},
                    "b": {"outcomes": ["2", "3"], "payout": 1},
                },
            }
        ],
    }
    r = client.post(
        f"/admin/games/{game_id}/variants",
        json={"name": "solapada", "house_edge": 0.05, "config": config},
        headers=auth(admin_token),
    )
    assert r.status_code == 422
    assert "ya pertenecen a otro grupo" in r.text


def test_variante_con_categorias_de_id_repetido_es_rechazada(
    client: TestClient, admin_token: str
) -> None:
    game_id = _crear_juego(client, admin_token)
    cat = {"id": "color", "label": "Color", "groups": {"a": {"outcomes": ["1"], "payout": 1}}}
    r = client.post(
        f"/admin/games/{game_id}/variants",
        json={
            "name": "repetida",
            "house_edge": 0.05,
            "config": {"possible_outcomes": ["1", "2"], "categories": [cat, cat]},
        },
        headers=auth(admin_token),
    )
    assert r.status_code == 422
    assert "mismo id" in r.text


def test_variante_con_payout_cero_es_rechazada(client: TestClient, admin_token: str) -> None:
    game_id = _crear_juego(client, admin_token)
    config = {
        "possible_outcomes": ["1", "2"],
        "categories": [
            {"id": "x", "label": "X", "groups": {"a": {"outcomes": ["1"], "payout": 0}}}
        ],
    }
    r = client.post(
        f"/admin/games/{game_id}/variants",
        json={"name": "sinpago", "house_edge": 0.05, "config": config},
        headers=auth(admin_token),
    )
    assert r.status_code == 422


def test_nombre_de_variante_duplicado_en_el_mismo_juego_es_rechazado(
    client: TestClient, admin_token: str
) -> None:
    game_id = _crear_juego(client, admin_token)
    body = {"name": "two_d6", "house_edge": 0.05, "config": DADOS_CONFIG}
    r1 = client.post(f"/admin/games/{game_id}/variants", json=body, headers=auth(admin_token))
    r2 = client.post(f"/admin/games/{game_id}/variants", json=body, headers=auth(admin_token))
    assert r1.status_code == 201
    assert r2.status_code == 409


def test_editar_variante_sin_tocar_config(client: TestClient, admin_token: str) -> None:
    game_id = _crear_juego(client, admin_token)
    variant = client.post(
        f"/admin/games/{game_id}/variants",
        json={"name": "two_d6", "house_edge": 0.05, "config": DADOS_CONFIG},
        headers=auth(admin_token),
    ).json()

    r = client.patch(
        f"/admin/games/{game_id}/variants/{variant['id']}",
        json={"active": False},
        headers=auth(admin_token),
    )
    assert r.status_code == 200
    assert r.json()["active"] is False
    # La config no se toca si no viene en el request.
    assert r.json()["config"] == variant["config"]


def test_variante_de_otro_juego_da_404(client: TestClient, admin_token: str) -> None:
    game_a = _crear_juego(client, admin_token)
    game_b = _crear_juego(client, admin_token)
    variant = client.post(
        f"/admin/games/{game_a}/variants",
        json={"name": "two_d6", "house_edge": 0.05, "config": DADOS_CONFIG},
        headers=auth(admin_token),
    ).json()
    r = client.patch(
        f"/admin/games/{game_b}/variants/{variant['id']}",
        json={"active": False},
        headers=auth(admin_token),
    )
    assert r.status_code == 404


# ---------- Juegos publicos ----------


def test_usuario_normal_solo_ve_juegos_y_variantes_activos(
    client: TestClient, admin_token: str, user_token: str
) -> None:
    game_id = _crear_juego(client, admin_token)
    client.post(
        f"/admin/games/{game_id}/variants",
        json={"name": "inactiva", "house_edge": 0.05, "config": DADOS_CONFIG, "active": False},
        headers=auth(admin_token),
    )
    client.post(
        f"/admin/games/{game_id}/variants",
        json={"name": "activa", "house_edge": 0.05, "config": DADOS_CONFIG, "active": True},
        headers=auth(admin_token),
    )

    r = client.get(f"/games/{game_id}/variants", headers=auth(user_token))
    assert r.status_code == 200
    assert [v["name"] for v in r.json()] == ["activa"]

    # El admin sí ve ambas.
    r = client.get(f"/games/{game_id}/variants", headers=auth(admin_token))
    assert sorted(v["name"] for v in r.json()) == ["activa", "inactiva"]


def test_include_inactive_requiere_admin(client: TestClient, user_token: str) -> None:
    assert client.get("/games", params={"include_inactive": True},
                      headers=auth(user_token)).status_code == 403
    assert client.get("/games", headers=auth(user_token)).status_code == 200


def test_ruleta_precargada_aparece_con_sus_dos_variantes(
    client: TestClient, admin_token: str
) -> None:
    """El seed no corre en la base de test, así que se crea aquí la misma forma:
    lo que se verifica es que el listado devuelva la config completa."""
    game_id = _crear_juego(client, admin_token)
    for nombre in ("european", "american"):
        client.post(
            f"/admin/games/{game_id}/variants",
            json={"name": nombre, "house_edge": 0.027, "config": DADOS_CONFIG},
            headers=auth(admin_token),
        )
    r = client.get("/games", headers=auth(admin_token))
    juego = next(g for g in r.json() if g["id"] == game_id)
    assert sorted(v["name"] for v in juego["variants"]) == ["american", "european"]


# ---------- Usuarios ----------


def test_listar_usuarios_y_cambiar_acceso(client: TestClient, admin_token: str) -> None:
    email = f"objetivo-{uuid.uuid4().hex[:8]}@ejemplo.com"
    creado = client.post(
        "/auth/register", json={"email": email, "password": "clave-segura-123"}
    ).json()["user"]
    assert creado["access_type"] == "trial"

    r = client.get("/admin/users", headers=auth(admin_token))
    assert r.status_code == 200
    assert email in [u["email"] for u in r.json()]

    r = client.patch(
        f"/admin/users/{creado['id']}/access",
        json={"access_type": "full"},
        headers=auth(admin_token),
    )
    assert r.status_code == 200
    assert r.json()["access_type"] == "full"


def test_access_type_invalido_es_rechazado(client: TestClient, admin_token: str) -> None:
    users = client.get("/admin/users", headers=auth(admin_token)).json()
    r = client.patch(
        f"/admin/users/{users[0]['id']}/access",
        json={"access_type": "premium"},
        headers=auth(admin_token),
    )
    assert r.status_code == 422


# ---------- Variante por id (la usa la vista de sesion) ----------


def test_un_usuario_normal_puede_leer_la_variante_de_su_sesion(
    client: TestClient, user_token: str, admin_token: str
) -> None:
    """La vista de ruleta necesita el `categories_json` y no es admin."""
    sufijo = uuid.uuid4().hex[:8]
    game = client.post(
        "/admin/games",
        json={"name": f"Ruleta {sufijo}", "type": f"roulette_{sufijo}", "active": True},
        headers=auth(admin_token),
    ).json()
    variant = client.post(
        f"/admin/games/{game['id']}/variants",
        json={"name": "mini", "house_edge": 0.1429, "config": DADOS_CONFIG},
        headers=auth(admin_token),
    ).json()

    r = client.get(f"/games/variants/{variant['id']}", headers=auth(user_token))
    assert r.status_code == 200
    assert r.json()["id"] == variant["id"]
    assert r.json()["config"]["possible_outcomes"]


def test_una_variante_desactivada_sigue_siendo_legible(
    client: TestClient, user_token: str, admin_token: str
) -> None:
    """Desactivarla impide abrir sesiones nuevas, no romper las ya abiertas."""
    sufijo = uuid.uuid4().hex[:8]
    game = client.post(
        "/admin/games",
        json={"name": f"Ruleta {sufijo}", "type": f"roulette_{sufijo}", "active": True},
        headers=auth(admin_token),
    ).json()
    variant = client.post(
        f"/admin/games/{game['id']}/variants",
        json={"name": "mini", "house_edge": 0.1429, "config": DADOS_CONFIG},
        headers=auth(admin_token),
    ).json()
    client.patch(
        f"/admin/games/{game['id']}/variants/{variant['id']}",
        json={"active": False},
        headers=auth(admin_token),
    )

    r = client.get(f"/games/variants/{variant['id']}", headers=auth(user_token))
    assert r.status_code == 200
    assert r.json()["active"] is False


def test_variante_inexistente_da_404(client: TestClient, user_token: str) -> None:
    r = client.get(f"/games/variants/{uuid.uuid4()}", headers=auth(user_token))
    assert r.status_code == 404


def test_la_variante_requiere_autenticacion(client: TestClient) -> None:
    assert client.get(f"/games/variants/{uuid.uuid4()}").status_code == 401
