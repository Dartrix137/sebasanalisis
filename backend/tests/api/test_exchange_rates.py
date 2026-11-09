"""Consultar y guardar las tasas de la factura (`core/exchange_rates.py`).

Las fuentes van sobre un `httpx.MockTransport`: ningun test sale a la red. Las
respuestas imitan las reales (datos.gov.co y el BCE, consultadas el
2026-11-09).
"""

from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select, text

from app.core.exchange_rates import ECB_URL, TRM_URL, RateSources, RateUnavailable, rates_for
from app.models import ExchangeRate

TRM_FILAS = {
    "2026-11-08": [{"valor": "3237.83", "unidad": "COP",
                    "vigenciadesde": "2026-11-07T00:00:00.000", "vigenciahasta": "2026-11-09T00:00:00.000"}],
    "2026-11-06": [{"valor": "3230.10", "unidad": "COP",
                    "vigenciadesde": "2026-11-06T00:00:00.000", "vigenciahasta": "2026-11-06T00:00:00.000"}],
}

BCE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-11-09"><Cube currency="USD" rate="1.1193"/></Cube>
    <Cube time="2026-11-06"><Cube currency="USD" rate="1.1210"/></Cube>
    <Cube time="2026-11-05"><Cube currency="USD" rate="1.1224"/></Cube>
  </Cube>
</gesmes:Envelope>"""


class Fuentes:
    """Las dos fuentes simuladas, con lo que les llego."""

    def __init__(self, *, bce: bytes = BCE_XML, trm_status: int = 200) -> None:
        self.bce = bce
        self.trm_status = trm_status
        self.pedidos: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.pedidos.append(request)
        url = str(request.url)
        if url.startswith(TRM_URL):
            if self.trm_status != 200:
                return httpx.Response(self.trm_status, json={"error": True})
            where = request.url.params["$where"]
            dia = where.split("'")[1][:10]
            return httpx.Response(200, json=TRM_FILAS.get(dia, []))
        if url == ECB_URL:
            return httpx.Response(200, content=self.bce)
        return httpx.Response(404)

    def cliente(self, token: str = "") -> RateSources:
        return RateSources(app_token=token, transport=httpx.MockTransport(self))


@pytest.fixture(autouse=True)
def tasas_limpias(db):
    db.execute(text("DELETE FROM exchange_rates"))
    db.commit()
    yield
    db.rollback()
    db.execute(text("DELETE FROM exchange_rates"))
    db.commit()


def test_un_pago_en_euros_toma_la_trm_y_la_del_bce_del_dia(db) -> None:
    fuentes = Fuentes()
    tasas = rates_for(db, date(2026, 11, 6), "EUR", fuentes.cliente())
    assert tasas is not None
    assert tasas.trm.value == Decimal("3230.10") and tasas.eur_usd is not None
    assert tasas.eur_usd.value == Decimal("1.1210")
    assert tasas.as_fx().usd_cop == Decimal("3230.10")
    # Quedaron guardadas, con su fuente.
    guardadas = {(r.pair, r.valid_from) for r in db.scalars(select(ExchangeRate))}
    assert ("USD/COP", date(2026, 11, 6)) in guardadas
    assert ("EUR/USD", date(2026, 11, 5)) in guardadas and len(guardadas) == 4


def test_un_domingo_usa_la_trm_del_fin_de_semana_y_la_del_bce_del_viernes(db) -> None:
    tasas = rates_for(db, date(2026, 11, 8), "EUR", Fuentes().cliente())
    assert tasas is not None
    assert tasas.trm.valid_from == date(2026, 11, 7) and tasas.trm.value == Decimal("3237.83")
    assert tasas.eur_usd is not None and tasas.eur_usd.valid_from == date(2026, 11, 6)


def test_lo_guardado_no_se_vuelve_a_consultar(db) -> None:
    fuentes = Fuentes()
    rates_for(db, date(2026, 11, 6), "EUR", fuentes.cliente())
    antes = len(fuentes.pedidos)
    tasas = rates_for(db, date(2026, 11, 6), "EUR", fuentes.cliente())
    assert tasas is not None and len(fuentes.pedidos) == antes


def test_un_sabado_no_se_fia_de_lo_guardado_si_falta_el_viernes(db) -> None:
    # Se guardo el jueves 5 antes de que saliera el viernes 6.
    db.add(ExchangeRate(pair="EUR/USD", valid_from=date(2026, 11, 5), valid_to=date(2026, 11, 5),
                        rate=Decimal("1.1224"), source="prueba"))
    db.flush()
    tasas = rates_for(db, date(2026, 11, 7), "EUR",
                      Fuentes().cliente())  # sabado 7: TRM de esa fila no existe
    # Sin TRM del sabado 7 en la fuente simulada: espera.
    assert tasas is None
    TRM_FILAS["2026-11-07"] = TRM_FILAS["2026-11-08"]
    try:
        tasas = rates_for(db, date(2026, 11, 7), "EUR", Fuentes().cliente())
    finally:
        del TRM_FILAS["2026-11-07"]
    assert tasas is not None and tasas.eur_usd is not None
    assert tasas.eur_usd.valid_from == date(2026, 11, 6)


def test_un_dia_habil_cuya_tasa_del_bce_no_salio_espera(db) -> None:
    TRM_FILAS["2026-11-10"] = [{"valor": "3240.00", "unidad": "COP",
                                "vigenciadesde": "2026-11-10T00:00:00.000",
                                "vigenciahasta": "2026-11-10T00:00:00.000"}]
    try:
        assert rates_for(db, date(2026, 11, 10), "EUR", Fuentes().cliente()) is None
    finally:
        del TRM_FILAS["2026-11-10"]


def test_sin_trm_publicada_espera_y_no_consulta_el_bce(db) -> None:
    fuentes = Fuentes()
    assert rates_for(db, date(2026, 11, 4), "EUR", fuentes.cliente()) is None
    assert all(not str(p.url).startswith(ECB_URL) for p in fuentes.pedidos)


def test_un_pago_en_dolares_solo_necesita_la_trm(db) -> None:
    fuentes = Fuentes()
    tasas = rates_for(db, date(2026, 11, 6), "USD", fuentes.cliente())
    assert tasas is not None and tasas.eur_usd is None
    assert all(not str(p.url).startswith(ECB_URL) for p in fuentes.pedidos)


def test_una_fuente_caida_es_un_error_que_se_reintenta(db) -> None:
    with pytest.raises(RateUnavailable, match="HTTP 503"):
        rates_for(db, date(2026, 11, 6), "EUR", Fuentes(trm_status=503).cliente())
    with pytest.raises(RateUnavailable, match="BCE"):
        rates_for(db, date(2026, 11, 6), "EUR", Fuentes(bce=b"<roto").cliente())


def test_el_token_va_solo_a_datos_gov_y_sin_token_no_va(db) -> None:
    fuentes = Fuentes()
    rates_for(db, date(2026, 11, 6), "EUR", fuentes.cliente(token="token-de-prueba"))
    trm = [p for p in fuentes.pedidos if str(p.url).startswith(TRM_URL)]
    bce = [p for p in fuentes.pedidos if str(p.url) == ECB_URL]
    assert trm and all(p.headers["X-App-Token"] == "token-de-prueba" for p in trm)
    # El token de datos.gov.co no se le manda a un tercero.
    assert bce and all("X-App-Token" not in p.headers for p in bce)
    db.execute(text("DELETE FROM exchange_rates"))
    fuentes = Fuentes()
    rates_for(db, date(2026, 11, 6), "USD", fuentes.cliente())
    assert "X-App-Token" not in fuentes.pedidos[-1].headers


def test_un_token_rechazado_no_deja_sin_trm(db, caplog) -> None:
    fuentes = Fuentes()

    def responder(request: httpx.Request) -> httpx.Response:
        if "X-App-Token" in request.headers:
            fuentes.pedidos.append(request)
            return httpx.Response(
                403, json={"code": "permission_denied", "error": True,
                           "message": "Invalid app_token specified"}
            )
        return fuentes(request)

    sources = RateSources(app_token="una-api-key", transport=httpx.MockTransport(responder))
    tasas = rates_for(db, date(2026, 11, 6), "USD", sources)
    assert tasas is not None and tasas.trm.value == Decimal("3230.10")
    assert "rechazo DATOS_GOV_APP_TOKEN" in caplog.text
    # El valor del token no va al log.
    assert "una-api-key" not in caplog.text


def test_otro_error_con_token_no_se_disimula(db) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    sources = RateSources(app_token="t", transport=httpx.MockTransport(responder))
    with pytest.raises(RateUnavailable, match="HTTP 500"):
        rates_for(db, date(2026, 11, 6), "USD", sources)


def test_una_tasa_guardada_no_se_reemplaza(db) -> None:
    db.add(ExchangeRate(pair="USD/COP", valid_from=date(2026, 11, 6), valid_to=date(2026, 11, 6),
                        rate=Decimal("3000.00"), source="la que se uso"))
    db.flush()
    tasas = rates_for(db, date(2026, 11, 6), "USD", Fuentes().cliente())
    assert tasas is not None and tasas.trm.value == Decimal("3000.00")


def test_pesos_u_otra_moneda_no_piden_tasas(db) -> None:
    with pytest.raises(ValueError):
        rates_for(db, date(2026, 11, 6), "COP", Fuentes().cliente())
    with pytest.raises(ValueError):
        rates_for(db, date(2026, 11, 6), "GBP", Fuentes().cliente())
