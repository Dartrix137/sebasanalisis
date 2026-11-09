"""Leer las tasas de su fuente y elegir la del dia del pago
(`billing/exchange_rates.py`). Sin base de datos ni red."""

from datetime import date
from decimal import Decimal

import pytest

from app.billing.exchange_rates import (
    ECB_SOURCE,
    TRM_SOURCE,
    RatePeriod,
    RateSourceError,
    ecb_for,
    parse_ecb_xml,
    parse_trm_rows,
    trm_for,
)

# Filas reales de datos.gov.co (32sa-8pi3), consultadas el 2026-11-09.
FILAS_TRM = [
    {"valor": "3237.83", "unidad": "COP",
     "vigenciadesde": "2026-11-07T00:00:00.000", "vigenciahasta": "2026-11-09T00:00:00.000"},
    {"valor": "3221.19", "unidad": "COP",
     "vigenciadesde": "2026-11-05T00:00:00.000", "vigenciahasta": "2026-11-05T00:00:00.000"},
    {"valor": "3182.99", "unidad": "COP",
     "vigenciadesde": "2026-10-31T00:00:00.000", "vigenciahasta": "2026-11-03T00:00:00.000"},
]

# La forma del XML diario del BCE (comillas simples) ...
XML_DIARIO = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <Cube>
    <Cube time='2026-11-09'>
      <Cube currency='USD' rate='1.1193'/>
      <Cube currency='JPY' rate='176.79'/>
    </Cube>
  </Cube>
</gesmes:Envelope>"""

# ... y la del historico de 90 dias (comillas dobles, varios dias).
XML_90_DIAS = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-11-09"><Cube currency="USD" rate="1.1193"/><Cube currency="GBP" rate="0.83430"/></Cube>
    <Cube time="2026-11-06"><Cube currency="USD" rate="1.1210"/></Cube>
    <Cube time="2026-11-05"><Cube currency="USD" rate="1.1224"/></Cube>
  </Cube>
</gesmes:Envelope>"""


def _ecb(*dias: tuple[date, str]) -> list[RatePeriod]:
    return [RatePeriod("EUR/USD", d, d, Decimal(v), ECB_SOURCE) for d, v in dias]


# ---------- TRM ----------


def test_las_filas_de_la_trm_se_leen_con_su_vigencia_y_en_decimal() -> None:
    periodos = parse_trm_rows(FILAS_TRM)
    assert periodos[0] == RatePeriod(
        "USD/COP", date(2026, 11, 7), date(2026, 11, 9), Decimal("3237.83"), TRM_SOURCE
    )
    assert all(isinstance(p.value, Decimal) for p in periodos)


def test_un_fin_de_semana_usa_la_trm_que_lo_cubre() -> None:
    periodos = parse_trm_rows(FILAS_TRM)
    # Sabado 31, domingo 1, lunes festivo 2 y martes 3: la misma fila.
    for dia in (31, 1, 2, 3):
        mes = 10 if dia == 31 else 11
        encontrada = trm_for(date(2026, mes, dia), periodos)
        assert encontrada is not None and encontrada.value == Decimal("3182.99")
    encontrada = trm_for(date(2026, 11, 8), periodos)
    assert encontrada is not None and encontrada.value == Decimal("3237.83")


def test_un_dia_sin_trm_publicada_espera() -> None:
    assert trm_for(date(2026, 11, 4), parse_trm_rows(FILAS_TRM)) is None
    assert trm_for(date(2026, 11, 10), parse_trm_rows(FILAS_TRM)) is None


@pytest.mark.parametrize(
    "fila",
    [
        {"valor": "3237.83", "unidad": "USD", "vigenciadesde": "2026-11-07", "vigenciahasta": "2026-11-09"},
        {"valor": "abc", "unidad": "COP", "vigenciadesde": "2026-11-07", "vigenciahasta": "2026-11-09"},
        {"valor": "0", "unidad": "COP", "vigenciadesde": "2026-11-07", "vigenciahasta": "2026-11-09"},
        {"valor": 3237.83, "unidad": "COP", "vigenciadesde": "2026-11-07", "vigenciahasta": "2026-11-09"},
        {"valor": "3237.83", "unidad": "COP", "vigenciadesde": "2026-11-09", "vigenciahasta": "2026-11-07"},
        {"valor": "3237.83", "unidad": "COP", "vigenciadesde": "ayer", "vigenciahasta": "2026-11-09"},
    ],
)
def test_una_fila_rara_de_la_trm_se_rechaza(fila: dict[str, object]) -> None:
    with pytest.raises(RateSourceError):
        parse_trm_rows([fila])


def test_una_respuesta_que_no_es_lista_se_rechaza() -> None:
    with pytest.raises(RateSourceError):
        parse_trm_rows({"error": True})


def test_dos_trm_distintas_para_el_mismo_dia_es_un_error() -> None:
    periodos = parse_trm_rows(FILAS_TRM) + parse_trm_rows(
        [{"valor": "3000", "unidad": "COP", "vigenciadesde": "2026-11-08", "vigenciahasta": "2026-11-08"}]
    )
    with pytest.raises(RateSourceError, match="Dos TRM"):
        trm_for(date(2026, 11, 8), periodos)


# ---------- BCE ----------


def test_el_xml_diario_y_el_de_90_dias_se_leen_igual() -> None:
    assert parse_ecb_xml(XML_DIARIO) == _ecb((date(2026, 11, 9), "1.1193"))
    periodos = parse_ecb_xml(XML_90_DIAS)
    assert [p.valid_from for p in periodos] == [date(2026, 11, 9), date(2026, 11, 6), date(2026, 11, 5)]
    assert periodos[2].value == Decimal("1.1224") and periodos[2].source == ECB_SOURCE


@pytest.mark.parametrize(
    "xml",
    [
        b"no es xml",
        b"<Envelope/>",
        XML_DIARIO.replace(b"currency='USD'", b"currency='CAD'"),
        XML_DIARIO.replace(b"rate='1.1193'", b"rate='uno'"),
    ],
)
def test_un_xml_raro_del_bce_se_rechaza(xml: bytes) -> None:
    with pytest.raises(RateSourceError):
        parse_ecb_xml(xml)


def test_el_dia_con_tasa_usa_la_suya() -> None:
    encontrada = ecb_for(date(2026, 11, 6), parse_ecb_xml(XML_90_DIAS))
    assert encontrada is not None and encontrada.value == Decimal("1.1210")


def test_el_fin_de_semana_usa_la_del_viernes() -> None:
    periodos = parse_ecb_xml(XML_90_DIAS)
    for dia in (7, 8):  # sabado y domingo
        encontrada = ecb_for(date(2026, 11, dia), periodos)
        assert encontrada is not None and encontrada.valid_from == date(2026, 11, 6)


def test_el_fin_de_semana_no_espera_al_lunes() -> None:
    # El sabado todavia no hay tasa del lunes, y no hace falta.
    periodos = _ecb((date(2026, 11, 6), "1.1210"))
    encontrada = ecb_for(date(2026, 11, 7), periodos)
    assert encontrada is not None and encontrada.valid_from == date(2026, 11, 6)


def test_un_dia_habil_cuya_tasa_no_salio_todavia_espera() -> None:
    # Martes 10 por la manana: la ultima es la del lunes 9.
    assert ecb_for(date(2026, 11, 10), parse_ecb_xml(XML_90_DIAS)) is None


def test_un_dia_habil_de_cierre_usa_la_anterior_cuando_ya_salio_una_posterior() -> None:
    # Viernes Santo (2026-04-03) sin tasa; el martes ya publico.
    periodos = _ecb((date(2026, 4, 2), "1.0800"), (date(2026, 4, 7), "1.0850"))
    encontrada = ecb_for(date(2026, 4, 3), periodos)
    assert encontrada is not None and encontrada.valid_from == date(2026, 4, 2)
    # Lunes de Pascua: tambien la del jueves.
    encontrada = ecb_for(date(2026, 4, 6), periodos)
    assert encontrada is not None and encontrada.valid_from == date(2026, 4, 2)


def test_sin_ninguna_tasa_anterior_espera() -> None:
    assert ecb_for(date(2026, 11, 7), _ecb((date(2026, 11, 9), "1.1193"))) is None


def test_una_tasa_anterior_demasiado_vieja_es_un_error() -> None:
    periodos = _ecb((date(2026, 10, 1), "1.10"), (date(2026, 11, 9), "1.1193"))
    with pytest.raises(RateSourceError, match="anterior"):
        ecb_for(date(2026, 11, 6), periodos)


def test_una_tasa_que_no_es_decimal_no_se_admite() -> None:
    with pytest.raises(RateSourceError):
        RatePeriod("EUR/USD", date(2026, 11, 9), date(2026, 11, 9), 1.1193, ECB_SOURCE)  # type: ignore[arg-type]
