"""Filtro de datos sensibles del monitoreo de errores (§13.6). Sin red ni base."""

import copy
from typing import Any

import pytest

from app.core import monitoring
from app.core.monitoring import FILTERED, init_monitoring, scrub_event


def _event(url: str, data: Any = None, query: str = "") -> dict[str, Any]:
    return {
        "request": {
            "url": url,
            "method": "POST",
            "query_string": query,
            "headers": {
                "Authorization": "Bearer token-secreto",
                "cookie": "sesion=abc",
                "Content-Type": "application/json",
            },
            "cookies": {"sesion": "abc"},
            "data": data,
        }
    }


def test_quita_cabeceras_de_autenticacion_y_cookies() -> None:
    event = scrub_event(_event("https://api.ejemplo.com/sessions", {"name": "Mesa"}))
    headers = event["request"]["headers"]
    assert headers["Authorization"] == FILTERED
    assert headers["cookie"] == FILTERED
    assert headers["Content-Type"] == "application/json"
    assert "cookies" not in event["request"]
    assert "token-secreto" not in str(event)


@pytest.mark.parametrize(
    "path",
    [
        "/auth/login",
        "/auth/reset-password",
        "/billing/subscriptions",
        "/billing/payment-method",
        "/webhooks/wompi",
    ],
)
def test_quita_el_cuerpo_de_las_rutas_sensibles(path: str) -> None:
    event = scrub_event(
        _event(
            f"https://api.ejemplo.com{path}",
            {"password": "clave-secreta", "card_token": "tok_123"},
            query="token=un-solo-uso",
        )
    )
    assert event["request"]["data"] == FILTERED
    assert event["request"]["query_string"] == FILTERED
    assert "clave-secreta" not in str(event)
    assert "tok_123" not in str(event)
    assert "un-solo-uso" not in str(event)


def test_conserva_el_cuerpo_de_las_rutas_de_juego() -> None:
    event = scrub_event(_event("https://api.ejemplo.com/sessions/abc/spins", {"result_value": "17"}))
    assert event["request"]["data"] == {"result_value": "17"}


def test_no_confunde_un_prefijo_parecido() -> None:
    """`/authors` no es `/auth`: el filtro compara segmentos, no texto."""
    event = scrub_event(_event("https://api.ejemplo.com/authors", {"nombre": "x"}))
    assert event["request"]["data"] == {"nombre": "x"}


def test_un_evento_sin_peticion_pasa_igual() -> None:
    event = {"message": "fallo el job de renovaciones"}
    assert scrub_event(copy.deepcopy(event)) == event


def test_sin_dsn_queda_desactivado(monkeypatch: pytest.MonkeyPatch) -> None:
    llamadas: list[dict[str, Any]] = []
    monkeypatch.setattr(monitoring.sentry_sdk, "init", lambda **kw: llamadas.append(kw))

    assert init_monitoring("") is False
    assert llamadas == []


def test_con_dsn_se_activa_sin_datos_personales(monkeypatch: pytest.MonkeyPatch) -> None:
    llamadas: list[dict[str, Any]] = []
    monkeypatch.setattr(monitoring.sentry_sdk, "init", lambda **kw: llamadas.append(kw))

    assert init_monitoring("https://clave@errores.ejemplo.com/1") is True
    (config,) = llamadas
    assert config["send_default_pii"] is False
    assert config["include_local_variables"] is False
    assert config["before_send"] is scrub_event
