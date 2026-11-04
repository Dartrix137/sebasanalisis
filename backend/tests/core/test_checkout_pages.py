"""La pagina de pago de un solo uso y su CSP (`core/checkout_pages.py`)."""

import base64
import hashlib

import pytest

from app.core import checkout_pages


@pytest.fixture(autouse=True)
def limpio():
    checkout_pages.clear()
    yield
    checkout_pages.clear()


def _huella(script: str) -> str:
    return f"'sha256-{base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()}'"


def test_una_pagina_se_entrega_una_sola_vez() -> None:
    token = checkout_pages.put("<p>hola</p>", now=0)
    pagina = checkout_pages.take(token, now=1)
    assert pagina is not None and pagina.html == "<p>hola</p>"
    assert checkout_pages.take(token, now=2) is None


def test_un_enlace_vencido_o_inventado_no_entrega_nada() -> None:
    token = checkout_pages.put("<p>hola</p>", now=0)
    assert checkout_pages.take(token, now=checkout_pages.TTL_SECONDS) is None
    assert checkout_pages.take("inventado", now=0) is None


def test_se_guarda_la_huella_del_enlace_y_no_el_enlace() -> None:
    token = checkout_pages.put("<p>x</p>", now=0)
    assert token not in checkout_pages._pages
    assert len(token) >= 40


def test_las_vencidas_salen_al_guardar_y_hay_un_tope(monkeypatch) -> None:
    checkout_pages.put("a", now=0)
    checkout_pages.put("b", now=checkout_pages.TTL_SECONDS + 1)
    assert len(checkout_pages._pages) == 1
    monkeypatch.setattr(checkout_pages, "MAX_PAGES", 2)
    primero = checkout_pages.put("c", now=checkout_pages.TTL_SECONDS + 2)
    checkout_pages.put("d", now=checkout_pages.TTL_SECONDS + 3)
    assert len(checkout_pages._pages) == 2
    assert checkout_pages.take(primero, now=checkout_pages.TTL_SECONDS + 4) is not None


def test_la_csp_deja_correr_solo_los_scripts_de_la_pagina() -> None:
    script = "document.getElementById('tpv').submit();"
    html = (
        '<form id="tpv" action="https://sis-t.redsys.es:25443/sis/realizarPago" method="POST">'
        f"</form><script>{script}</script>"
    )
    directivas = dict(d.strip().split(" ", 1) for d in checkout_pages.page_csp(html).split(";"))
    assert directivas["script-src"] == _huella(script)
    assert directivas["form-action"] == "'self' https://sis-t.redsys.es:25443"
    assert directivas["default-src"] == "'none'" and directivas["frame-ancestors"] == "'none'"
    assert directivas["base-uri"] == "'none'"


def test_los_manejadores_en_linea_van_con_su_huella() -> None:
    html = '<body onload="document.forms[0].submit()"><form action="https://pay.ebanx.com/x"></form></body>'
    csp = checkout_pages.page_csp(html)
    assert "'unsafe-hashes' " + _huella("document.forms[0].submit()") in csp
    assert "form-action 'self' https://pay.ebanx.com" in csp


def test_un_script_externo_por_https_entra_por_su_origen() -> None:
    csp = checkout_pages.page_csp('<script src="https://cdn.ebanx.com/js/x.js"></script>')
    assert "script-src https://cdn.ebanx.com" in csp


def test_sin_scripts_no_corre_ninguno() -> None:
    csp = checkout_pages.page_csp('<meta http-equiv="refresh" content="0;url=https://pay.ebanx.com/x">')
    assert "script-src 'none'" in csp and "form-action 'self';" in csp


def test_lo_que_no_va_por_https_no_entra_en_la_csp() -> None:
    html = '<form action="http://inseguro.com/x"></form><script src="http://inseguro.com/a.js"></script>'
    csp = checkout_pages.page_csp(html)
    assert "inseguro.com" not in csp


def test_el_origen_de_regreso_entra_en_form_action() -> None:
    """Chrome aplica `form-action` a la redireccion que sigue al envio: la vuelta
    a la aplicacion tiene que estar permitida."""
    token = checkout_pages.put("<form action='/x'></form>", return_url="http://localhost:3000/", now=0)
    pagina = checkout_pages.take(token, now=1)
    assert pagina is not None
    assert "form-action 'self' http://localhost:3000;" in pagina.csp
    csp = checkout_pages.page_csp("<p></p>", form_origins=("https://sebasanalisis.com",))
    assert "form-action 'self' https://sebasanalisis.com;" in csp
