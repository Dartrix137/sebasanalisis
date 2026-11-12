"""Guias de uso de un juego: videos de YouTube y un PDF (2026-11-12).

`GET /games/{slug}/guides` pide acceso al juego, y `POST /auth/me/guides-seen`
anota una vez que la cuenta cerro la ventana del inicio.
"""

import pytest
from fastapi.testclient import TestClient

from app.core import guides
from app.core.guides import GameGuides, GuidePdf, GuideVideo
from tests.api.conftest import auth, register_raw
from tests.api.test_multijuego import (
    PASSWORD,
    _crear_juego,
    _crear_plan,
    _juegos_del_plan,
    _suscriptor,
)

GUIAS = GameGuides(
    videos=(
        GuideVideo(title="Parte 1", youtube_id="AbCdEfGhIj1"),
        GuideVideo(title="Parte 2", youtube_id="AbCdEfGhIj2"),
    ),
    pdf=GuidePdf(
        title="Guía en PDF",
        url="https://res.cloudinary.com/demo/image/upload/fl_attachment/guia.pdf",
    ),
)


@pytest.fixture
def juego(client: TestClient, admin_token: str, monkeypatch) -> dict:
    """Un juego de prueba con guias en el catalogo."""
    creado = _crear_juego(client, admin_token)
    monkeypatch.setitem(guides.GUIDES, creado["type"], GUIAS)
    return creado


def test_el_catalogo_real_tiene_ids_y_urls_validos() -> None:
    for entrada in guides.GUIDES.values():
        guides.validate(entrada)


def test_validate_rechaza_un_id_o_un_pdf_mal_copiados() -> None:
    with pytest.raises(ValueError):
        guides.validate(GameGuides(videos=(GuideVideo("x", "https://youtu.be/x"),), pdf=None))
    with pytest.raises(ValueError):
        guides.validate(GameGuides(videos=(), pdf=GuidePdf("x", "https://drive.google.com/x")))


def test_con_acceso_recibe_las_guias(client: TestClient, user_token: str, juego: dict) -> None:
    r = client.get(f"/games/{juego['slug']}/guides", headers=auth(user_token))
    assert r.status_code == 200, r.text
    assert r.json() == {
        "videos": [
            {"title": "Parte 1", "youtube_id": "AbCdEfGhIj1"},
            {"title": "Parte 2", "youtube_id": "AbCdEfGhIj2"},
        ],
        "pdf": {"title": "Guía en PDF", "url": GUIAS.pdf.url},  # type: ignore[union-attr]
    }


def test_un_juego_sin_guias_responde_vacio(
    client: TestClient, admin_token: str, user_token: str
) -> None:
    sin_guias = _crear_juego(client, admin_token)
    r = client.get(f"/games/{sin_guias['slug']}/guides", headers=auth(user_token))
    assert r.status_code == 200, r.text
    assert r.json() == {"videos": [], "pdf": None}


def test_sin_acceso_responde_403(client: TestClient, juego: dict) -> None:
    token = register_raw(client, "guias-sin-acceso@ejemplo.com", PASSWORD)["access_token"]
    r = client.get(f"/games/{juego['slug']}/guides", headers=auth(token))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "no_access"


def test_un_juego_fuera_del_plan_responde_403(
    client: TestClient, admin_token: str, db, juego: dict
) -> None:
    otro = _crear_juego(client, admin_token)
    plan = _crear_plan(client, admin_token)
    assert _juegos_del_plan(client, admin_token, plan["id"], [otro["id"]]).status_code == 200
    token = _suscriptor(client, db, plan["id"])

    r = client.get(f"/games/{juego['slug']}/guides", headers=auth(token))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "game_not_in_plan"


def test_un_juego_inexistente_u_oculto_responde_404(
    client: TestClient, admin_token: str, user_token: str, monkeypatch
) -> None:
    assert client.get("/games/no-existe/guides", headers=auth(user_token)).status_code == 404

    oculto = _crear_juego(client, admin_token, status="hidden")
    monkeypatch.setitem(guides.GUIDES, oculto["type"], GUIAS)
    r = client.get(f"/games/{oculto['slug']}/guides", headers=auth(user_token))
    assert r.status_code == 404
    # El administrador lo ve, para probarlo antes de publicarlo.
    r = client.get(f"/games/{oculto['slug']}/guides", headers=auth(admin_token))
    assert r.status_code == 200


def test_guias_vistas_se_anota_una_sola_vez(client: TestClient, user_token: str) -> None:
    assert client.get("/auth/me", headers=auth(user_token)).json()["guides_seen_at"] is None

    r = client.post("/auth/me/guides-seen", headers=auth(user_token))
    assert r.status_code == 200, r.text
    primera = r.json()["guides_seen_at"]
    assert primera is not None

    r = client.post("/auth/me/guides-seen", headers=auth(user_token))
    assert r.json()["guides_seen_at"] == primera
    assert client.get("/auth/me", headers=auth(user_token)).json()["guides_seen_at"] == primera


def test_apagadas_responden_vacio(client: TestClient, user_token: str, juego: dict, monkeypatch) -> None:
    """`GUIDES_ENABLED=false` solo existe para Playwright: ahi la ventana taparia el inicio."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "guides_enabled", False)
    r = client.get(f"/games/{juego['slug']}/guides", headers=auth(user_token))
    assert r.status_code == 200
    assert r.json() == {"videos": [], "pdf": None}
