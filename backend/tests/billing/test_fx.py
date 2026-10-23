"""Fecha de la operacion y conversion a pesos (docs/PLATAFORMA_COMPLETA.md §3.17).
Sin base de datos ni red."""

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.billing.fx import COLOMBIA, Rates, operation_date, to_cop_cents

TRM = Decimal("4012.35")
EUR_USD = Decimal("1.0855")


# ---------- Dia de la operacion ----------


def test_antes_de_las_cinco_utc_todavia_es_el_dia_anterior_en_colombia() -> None:
    assert operation_date(datetime(2026, 10, 24, 3, 0, tzinfo=UTC)) == date(2026, 10, 23)
    assert operation_date(datetime(2026, 10, 24, 4, 59, 59, tzinfo=UTC)) == date(2026, 10, 23)


def test_desde_las_cinco_utc_ya_es_el_dia_siguiente_en_colombia() -> None:
    assert operation_date(datetime(2026, 10, 24, 5, 0, tzinfo=UTC)) == date(2026, 10, 24)


def test_cualquier_zona_cuenta_igual() -> None:
    madrid = timezone(timedelta(hours=2))
    # 06:30 en Madrid son las 23:30 del dia anterior en Colombia.
    assert operation_date(datetime(2026, 10, 24, 6, 30, tzinfo=madrid)) == date(2026, 10, 23)
    assert operation_date(datetime(2026, 10, 23, 23, 30, tzinfo=COLOMBIA)) == date(2026, 10, 23)


def test_una_hora_sin_zona_se_rechaza() -> None:
    with pytest.raises(ValueError, match="zona horaria"):
        operation_date(datetime(2026, 10, 24, 3, 0))


# ---------- Conversion a pesos ----------


def test_un_pago_en_pesos_no_necesita_tasas() -> None:
    assert to_cop_cents(10_000_000, "COP", Rates()) == 10_000_000


def test_un_pago_en_dolares_se_convierte_con_la_trm() -> None:
    # 100 USD a 4012,35 = 401.235 COP.
    assert to_cop_cents(10_000, "USD", Rates(usd_cop=TRM)) == 40_123_500


def test_un_pago_en_euros_pasa_por_dolares_y_despues_por_la_trm() -> None:
    # 150 EUR x 1,0855 x 4012,35 = 653.310,88875 COP: sube al centavo.
    assert to_cop_cents(15_000, "EUR", Rates(eur_usd=EUR_USD, usd_cop=TRM)) == 65_331_089


def test_se_redondea_una_sola_vez_al_final() -> None:
    # 10,01 EUR = 10,865855 USD. Redondeado en dolares (10,87 USD) daria
    # 43.614,24 COP; sin redondeo intermedio da 43.597,61 COP.
    assert to_cop_cents(1_001, "EUR", Rates(eur_usd=EUR_USD, usd_cop=TRM)) == 4_359_761


def test_la_mitad_exacta_sube() -> None:
    # 1 centavo de dolar a 4000,5 = 4000,5 centavos de peso.
    assert to_cop_cents(1, "USD", Rates(usd_cop=Decimal("4000.5"))) == 4_001


def test_las_tasas_que_no_se_usan_no_estorban() -> None:
    assert to_cop_cents(10_000, "USD", Rates(eur_usd=EUR_USD, usd_cop=TRM)) == 40_123_500


@pytest.mark.parametrize(
    ("currency", "rates", "falta"),
    [
        ("USD", Rates(), "usd_cop"),
        ("EUR", Rates(usd_cop=TRM), "eur_usd"),
        ("EUR", Rates(eur_usd=EUR_USD), "usd_cop"),
    ],
)
def test_sin_la_tasa_que_hace_falta_no_se_convierte(currency: str, rates: Rates, falta: str) -> None:
    with pytest.raises(ValueError, match=falta):
        to_cop_cents(10_000, currency, rates)


def test_una_moneda_que_no_se_conoce_se_rechaza() -> None:
    with pytest.raises(ValueError, match="GBP"):
        to_cop_cents(10_000, "GBP", Rates(eur_usd=EUR_USD, usd_cop=TRM))


@pytest.mark.parametrize("monto", [0, -100])
def test_el_monto_debe_ser_positivo(monto: int) -> None:
    with pytest.raises(ValueError):
        to_cop_cents(monto, "COP", Rates())


@pytest.mark.parametrize("monto", [100.0, True, Decimal("100")])
def test_el_monto_va_en_centavos_enteros(monto: object) -> None:
    with pytest.raises(TypeError):
        to_cop_cents(monto, "COP", Rates())  # type: ignore[arg-type]


# ---------- Tasas ----------


@pytest.mark.parametrize("tasa", [4012.35, 4012, True])
def test_una_tasa_que_no_es_decimal_se_rechaza(tasa: object) -> None:
    with pytest.raises(TypeError, match="Decimal"):
        Rates(usd_cop=tasa)  # type: ignore[arg-type]


@pytest.mark.parametrize("tasa", ["0", "-1", "NaN", "Infinity"])
def test_una_tasa_debe_ser_un_numero_mayor_que_cero(tasa: str) -> None:
    with pytest.raises(ValueError, match="mayor que cero"):
        Rates(eur_usd=Decimal(tasa))
