"""Verificacion contra bots con Turnstile (core/bot_check.py), sin salir a la red."""

from urllib.parse import parse_qs

import httpx
import pytest

from app.core.bot_check import (
    SITEVERIFY_URL,
    DisabledBotChecker,
    TurnstileChecker,
    build_bot_checker,
)
from app.core.config import Settings


def _checker(respuesta: dict | Exception, pedidos: list[httpx.Request] | None = None) -> TurnstileChecker:
    def manejar(request: httpx.Request) -> httpx.Response:
        if pedidos is not None:
            pedidos.append(request)
        if isinstance(respuesta, Exception):
            raise respuesta
        return httpx.Response(200, json=respuesta)

    return TurnstileChecker(
        site_key="llave-del-sitio", secret_key="secreto", transport=httpx.MockTransport(manejar)
    )


def test_un_token_valido_pasa_y_va_con_el_secreto_y_la_ip() -> None:
    pedidos: list[httpx.Request] = []
    checker = _checker({"success": True, "action": "login"}, pedidos)
    assert checker.verify("token-1", remote_ip="203.0.113.5", action="login")
    (pedido,) = pedidos
    assert str(pedido.url) == SITEVERIFY_URL
    assert pedido.method == "POST"
    assert parse_qs(pedido.content.decode()) == {
        "secret": ["secreto"],
        "response": ["token-1"],
        "remoteip": ["203.0.113.5"],
    }


def test_un_token_rechazado_no_pasa() -> None:
    checker = _checker({"success": False, "error-codes": ["timeout-or-duplicate"]})
    assert not checker.verify("token-1", remote_ip=None, action="login")


def test_un_token_de_otro_formulario_no_pasa() -> None:
    checker = _checker({"success": True, "action": "login"})
    assert not checker.verify("token-1", remote_ip=None, action="register")


def test_sin_accion_en_la_respuesta_pasa() -> None:
    # Las llaves de prueba de Cloudflare no devuelven accion.
    assert _checker({"success": True}).verify("token-1", remote_ip=None, action="register")


@pytest.mark.parametrize("token", [None, "", "x" * 2049])
def test_sin_token_o_demasiado_largo_no_pasa_ni_sale_a_la_red(token: str | None) -> None:
    pedidos: list[httpx.Request] = []
    assert not _checker({"success": True}, pedidos).verify(token, remote_ip=None, action="login")
    assert pedidos == []


def test_si_cloudflare_no_responde_no_pasa() -> None:
    caido = _checker(httpx.ConnectError("sin red"))
    assert not caido.verify("token-1", remote_ip=None, action="login")


def test_una_respuesta_que_no_es_json_no_pasa() -> None:
    checker = TurnstileChecker(
        site_key="s",
        secret_key="x",
        transport=httpx.MockTransport(lambda _: httpx.Response(502, text="<html>")),
    )
    assert not checker.verify("token-1", remote_ip=None, action="login")


def test_sin_llaves_queda_apagada() -> None:
    checker = build_bot_checker(Settings(turnstile_site_key="", turnstile_secret_key=""))
    assert isinstance(checker, DisabledBotChecker)
    assert checker.site_key is None
    assert checker.verify(None, remote_ip=None, action="login")


def test_con_las_dos_llaves_usa_turnstile() -> None:
    checker = build_bot_checker(Settings(turnstile_site_key="sitio", turnstile_secret_key="secreto"))
    assert isinstance(checker, TurnstileChecker)
    assert checker.site_key == "sitio"


@pytest.mark.parametrize(("sitio", "secreto"), [("sitio", ""), ("", "secreto")])
def test_con_una_sola_llave_no_arranca(sitio: str, secreto: str) -> None:
    with pytest.raises(ValueError, match="van juntas"):
        build_bot_checker(Settings(turnstile_site_key=sitio, turnstile_secret_key=secreto))
