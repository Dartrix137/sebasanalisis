"""Periodos que compra un pago (§3.5 y §3.10). Sin base ni red."""

from datetime import UTC, datetime, timedelta

import pytest

from app.billing.periods import add_interval, next_period

AHORA = datetime(2026, 10, 13, 15, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("inicio", "intervalo", "cuantos", "esperado"),
    [
        (datetime(2026, 10, 13, 15, 30, tzinfo=UTC), "month", 1, datetime(2026, 11, 13, 15, 30, tzinfo=UTC)),
        # El plan de dos meses.
        (datetime(2026, 10, 13, tzinfo=UTC), "month", 2, datetime(2026, 12, 13, tzinfo=UTC)),
        # Cruza el año.
        (datetime(2026, 12, 13, tzinfo=UTC), "month", 2, datetime(2027, 2, 13, tzinfo=UTC)),
        # El dia no existe en el mes de llegada: el ultimo de ese mes.
        (datetime(2027, 1, 31, tzinfo=UTC), "month", 1, datetime(2027, 2, 28, tzinfo=UTC)),
        (datetime(2028, 1, 31, tzinfo=UTC), "month", 1, datetime(2028, 2, 29, tzinfo=UTC)),
        (datetime(2026, 8, 31, tzinfo=UTC), "month", 1, datetime(2026, 9, 30, tzinfo=UTC)),
        (datetime(2026, 10, 13, tzinfo=UTC), "year", 1, datetime(2027, 10, 13, tzinfo=UTC)),
        (datetime(2028, 2, 29, tzinfo=UTC), "year", 1, datetime(2029, 2, 28, tzinfo=UTC)),
    ],
)
def test_add_interval(inicio, intervalo, cuantos, esperado) -> None:
    assert add_interval(inicio, intervalo, cuantos) == esperado


def test_add_interval_rechaza_un_periodo_sin_duracion() -> None:
    with pytest.raises(ValueError):
        add_interval(AHORA, "month", 0)


def test_el_primer_pago_cuenta_desde_el_momento_del_pago() -> None:
    periodo = next_period(AHORA, None, "month", 1)
    assert (periodo.start, periodo.end) == (AHORA, datetime(2026, 11, 13, 15, 30, tzinfo=UTC))


def test_pagar_antes_del_vencimiento_extiende_desde_el_vencimiento() -> None:
    """No se pierden los dias que quedaban (decidido el 2026-10-13)."""
    vence = AHORA + timedelta(days=5)
    periodo = next_period(AHORA, vence, "month", 1)
    assert periodo.start == vence
    assert periodo.end == datetime(2026, 11, 18, 15, 30, tzinfo=UTC)


def test_pagar_despues_del_vencimiento_cuenta_desde_el_pago() -> None:
    """No se cobran los dias en que no hubo acceso."""
    vencio = AHORA - timedelta(days=5)
    periodo = next_period(AHORA, vencio, "month", 1)
    assert periodo.start == AHORA


def test_pagar_justo_en_el_vencimiento_cuenta_desde_el_pago() -> None:
    assert next_period(AHORA, AHORA, "month", 2).end == datetime(2026, 12, 13, 15, 30, tzinfo=UTC)
