"""Ventanas y cuentas del resumen del admin (§4.7 y §4.9). Sin base ni red."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core.overview import monthly_cents, periods, rate_bp

BOGOTA = timezone(timedelta(hours=-5))


def _bogota(*args: int) -> datetime:
    return datetime(*args, tzinfo=BOGOTA)


def test_mes_en_curso_contra_el_mismo_tramo_del_anterior() -> None:
    ahora = _bogota(2026, 10, 14, 9, 30)
    p = periods(ahora.astimezone(UTC))

    assert p.current.start == _bogota(2026, 10, 1)
    assert p.current.end == ahora
    assert p.previous.start == _bogota(2026, 9, 1)
    assert p.previous.end == _bogota(2026, 9, 14, 9, 30)
    # Todo sale en UTC.
    assert p.current.start.tzinfo == UTC and p.current.start.hour == 5


def test_las_fronteras_son_medianoche_de_bogota_no_de_utc() -> None:
    # 1 de noviembre a las 03:00 UTC es todavia 31 de octubre en Bogota.
    p = periods(datetime(2026, 11, 1, 3, 0, tzinfo=UTC))
    assert p.current.start == _bogota(2026, 10, 1)
    assert p.previous.start == _bogota(2026, 9, 1)
    # Septiembre no tiene 31: el tramo anterior es el mes completo.
    assert p.previous.end == _bogota(2026, 10, 1)


def test_un_mes_mas_corto_termina_al_final_de_ese_mes() -> None:
    p = periods(_bogota(2026, 3, 31, 18, 0))
    assert (p.previous.start, p.previous.end) == (_bogota(2026, 2, 1), _bogota(2026, 3, 1))
    p = periods(_bogota(2028, 3, 29, 8, 0))  # 2028 es bisiesto
    assert p.previous.end == _bogota(2028, 2, 29, 8, 0)


def test_enero_se_compara_con_diciembre_del_ano_anterior() -> None:
    p = periods(_bogota(2027, 1, 10, 12, 0))
    assert p.current.start == _bogota(2027, 1, 1)
    assert (p.previous.start, p.previous.end) == (_bogota(2026, 12, 1), _bogota(2026, 12, 10, 12, 0))


def test_el_primer_instante_del_mes() -> None:
    p = periods(_bogota(2026, 10, 1))
    assert p.current.start == p.current.end == _bogota(2026, 10, 1)
    assert p.previous.start == p.previous.end == _bogota(2026, 9, 1)


@pytest.mark.parametrize(
    ("monto", "intervalo", "cuenta", "mensual"),
    [
        (10_000_000, "month", 1, 10_000_000),
        (15_000_000, "month", 2, 7_500_000),
        (12_000_001, "year", 1, 1_000_000),  # redondea hacia abajo al centavo
        (10_000_000, "month", 3, 3_333_333),
    ],
)
def test_llevar_un_cobro_a_un_mes(monto: int, intervalo: str, cuenta: int, mensual: int) -> None:
    assert monthly_cents(monto, intervalo, cuenta) == mensual


def test_tasa_en_puntos_basicos() -> None:
    assert rate_bp(1, 4) == 2_500
    assert rate_bp(1, 3) == 3_333
    assert rate_bp(0, 10) == 0
    assert rate_bp(3, 0) is None
