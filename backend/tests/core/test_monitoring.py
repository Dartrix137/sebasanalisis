"""Filtro de datos sensibles del monitoreo de errores (§13.6). Sin red ni base."""

import copy
import logging
from typing import Any

import httpx
import pytest
import sentry_sdk
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

from app.core import monitoring
from app.core.monitoring import (
    FILTERED,
    init_monitoring,
    quiet_http_client_logs,
    scrub_breadcrumb,
    scrub_event,
)


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
        "/webhooks/payments",
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


def test_quita_los_datos_del_comprador_al_abrir_un_pago() -> None:
    event = scrub_event(
        _event(
            "https://api.ejemplo.com/billing/subscriptions",
            {"payment_method": "ebanxyapeperu", "buyer": {"first_name": "Ana", "phone": "+51 999"}},
        )
    )
    assert "Ana" not in str(event) and "+51 999" not in str(event)


def test_quita_el_token_del_enlace_de_la_pagina_de_pago() -> None:
    event = scrub_event(_event("https://api.ejemplo.com/billing/checkout/tok-secreto-123?x=1"))
    assert event["request"]["url"] == f"https://api.ejemplo.com/billing/checkout/{FILTERED}"
    assert "tok-secreto-123" not in str(event)


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
    assert config["before_breadcrumb"] is scrub_breadcrumb


# ---------- Breadcrumbs: la query de las peticiones a otros servicios ----------

DOCUMENTO = "1234567890"
SIIGO_URL = f"https://api.siigo.com/v1/customers?identification={DOCUMENTO}"


def test_quita_la_query_de_un_breadcrumb_de_httpx() -> None:
    crumb = scrub_breadcrumb(
        {
            "type": "http",
            "category": "httplib",
            "data": {
                "url": "https://api.siigo.com/v1/customers",
                "http.method": "GET",
                "http.query": f"identification={DOCUMENTO}",
                "status_code": 200,
            },
        }
    )
    assert crumb["data"]["http.query"] == FILTERED
    assert crumb["data"]["url"] == "https://api.siigo.com/v1/customers"
    assert crumb["data"]["status_code"] == 200
    assert DOCUMENTO not in str(crumb)


def test_quita_la_query_de_la_url_dentro_de_un_mensaje_de_log() -> None:
    crumb = scrub_breadcrumb(
        {
            "type": "log",
            "category": "httpx",
            "message": f'HTTP Request: GET {SIIGO_URL} "HTTP/1.1 200 OK"',
        }
    )
    assert crumb["message"] == (
        f'HTTP Request: GET https://api.siigo.com/v1/customers?{FILTERED} "HTTP/1.1 200 OK"'
    )


def test_un_breadcrumb_sin_url_pasa_igual() -> None:
    crumb = {"type": "log", "category": "app.renewals", "message": "Renovaciones: 3 cobros"}
    assert scrub_breadcrumb(copy.deepcopy(crumb)) == crumb


class _Captura(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.envelopes: list[Envelope] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        self.envelopes.append(envelope)


def test_el_documento_de_una_consulta_a_siigo_no_llega_a_glitchtip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con el SDK de verdad: una peticion de httpx con el documento en la query y
    su linea de log en INFO, y despues un error reportado con sus breadcrumbs."""
    captura = _Captura()
    real_init = sentry_sdk.init
    monkeypatch.setattr(
        monitoring.sentry_sdk, "init", lambda **kw: real_init(transport=captura, **kw)
    )
    httpx_logger = logging.getLogger("httpx")
    nivel = httpx_logger.level
    httpx_logger.setLevel(logging.INFO)
    try:
        assert init_monitoring("https://clave@errores.ejemplo.com/1")
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as c:
            c.get(SIIGO_URL)
        sentry_sdk.capture_message("fallo la emision")
        sentry_sdk.flush()
    finally:
        httpx_logger.setLevel(nivel)
        sentry_sdk.get_client().close()
        sentry_sdk.get_global_scope().set_client(None)

    enviado = b"".join(e.serialize() for e in captura.envelopes)
    assert b"api.siigo.com/v1/customers" in enviado  # el breadcrumb salio
    assert DOCUMENTO.encode() not in enviado


def test_el_job_no_escribe_las_urls_de_httpx(caplog: pytest.LogCaptureFixture) -> None:
    nivel = logging.getLogger("httpx").level
    caplog.set_level(logging.INFO)  # como `basicConfig(level=INFO)` del job
    try:
        quiet_http_client_logs()
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as c:
            c.get(SIIGO_URL)
    finally:
        logging.getLogger("httpx").setLevel(nivel)
    assert DOCUMENTO not in caplog.text
