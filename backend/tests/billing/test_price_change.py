"""Cuando aplica el traslado de un precio (§4.10). Sin base ni red."""

from datetime import UTC, datetime, timedelta

import pytest

from app.billing.price_change import (
    INCREASE_NOTICE_DAYS,
    AppliedChange,
    Direction,
    PendingChange,
    charge_price,
    direction,
    effective_at,
    first_charge_with_new_price,
    price_at,
)

AHORA = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
AVISO = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


def test_la_direccion_sale_de_comparar_los_precios() -> None:
    assert direction(10_000_000, 12_000_000) is Direction.increase
    assert direction(12_000_000, 10_000_000) is Direction.decrease
    with pytest.raises(ValueError):
        direction(10_000_000, 10_000_000)


def test_una_subida_aplica_treinta_dias_despues_de_su_aviso() -> None:
    assert INCREASE_NOTICE_DAYS == 30
    cuando = effective_at(10_000_000, 12_000_000, registered_at=AHORA, notice_sent_at=AVISO)
    assert cuando == AVISO + timedelta(days=30)


def test_una_subida_sin_aviso_no_tiene_fecha() -> None:
    assert effective_at(10_000_000, 12_000_000, registered_at=AHORA, notice_sent_at=None) is None


def test_una_bajada_aplica_al_registrarse_aunque_el_aviso_no_haya_salido() -> None:
    assert effective_at(12_000_000, 10_000_000, registered_at=AHORA, notice_sent_at=None) == AHORA
    assert effective_at(12_000_000, 10_000_000, registered_at=AHORA, notice_sent_at=AVISO) == AHORA


def test_el_precio_que_corre_en_cada_momento() -> None:
    nuevo = PendingChange(new_price_cents=12_000_000, effective_at=AVISO + timedelta(days=30))
    assert price_at(10_000_000, None, AHORA) == 10_000_000
    assert price_at(10_000_000, nuevo, AVISO) == 10_000_000
    assert price_at(10_000_000, nuevo, AVISO + timedelta(days=30) - timedelta(seconds=1)) == 10_000_000
    # Desde ese instante, el nuevo.
    assert price_at(10_000_000, nuevo, AVISO + timedelta(days=30)) == 12_000_000
    sin_fecha = PendingChange(new_price_cents=12_000_000, effective_at=None)
    assert price_at(10_000_000, sin_fecha, AHORA + timedelta(days=365)) == 10_000_000


# El caso que lo origino (2026-10-15): bajada a 99.000 y vuelta a 100.000. La
# subida corre desde el 13 de noviembre y el periodo vence el 14: su primer
# intento es el 12.
VENCE = datetime(2026, 11, 14, 15, 0, tzinfo=UTC)
PRIMER_INTENTO = VENCE - timedelta(hours=48)
CORRE = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


def test_el_cobro_de_un_periodo_va_con_el_precio_de_su_primer_intento() -> None:
    subida = PendingChange(new_price_cents=10_000_000, effective_at=CORRE)
    # Antes de que el job la aplique: el primer intento es antes de que corra.
    assert charge_price(9_900_000, subida, [], PRIMER_INTENTO) == 9_900_000
    # El job ya la aplico (el congelado es 100.000) y el reintento del 13 o del
    # 14 sigue con 99.000.
    aplicada = AppliedChange(old_price_cents=9_900_000, new_price_cents=10_000_000, effective_at=CORRE)
    assert charge_price(10_000_000, None, [aplicada], PRIMER_INTENTO) == 9_900_000
    # El periodo siguiente ya va con el nuevo.
    siguiente = datetime(2026, 12, 12, 15, 0, tzinfo=UTC)
    assert charge_price(10_000_000, None, [aplicada], siguiente) == 10_000_000


def test_una_subida_que_corre_antes_del_primer_intento_se_cobra_en_ese_periodo() -> None:
    antes = PRIMER_INTENTO - timedelta(days=1)
    assert charge_price(9_900_000, PendingChange(10_000_000, antes), [], PRIMER_INTENTO) == 10_000_000
    aplicada = AppliedChange(old_price_cents=9_900_000, new_price_cents=10_000_000, effective_at=antes)
    assert charge_price(10_000_000, None, [aplicada], PRIMER_INTENTO) == 10_000_000
    # Justo en el primer intento ya corre.
    justa = AppliedChange(9_900_000, 10_000_000, effective_at=PRIMER_INTENTO)
    assert charge_price(10_000_000, None, [justa], PRIMER_INTENTO) == 10_000_000


def test_una_bajada_aplicada_entre_intentos_beneficia_al_reintento() -> None:
    bajada = AppliedChange(old_price_cents=10_000_000, new_price_cents=9_900_000, effective_at=CORRE)
    assert charge_price(9_900_000, None, [bajada], PRIMER_INTENTO) == 9_900_000


def test_el_primer_cobro_con_el_precio_nuevo() -> None:
    # Corre el 13 y el primer intento del periodo es el 12: el nuevo va en el
    # cobro del periodo siguiente, el 12 de diciembre.
    assert first_charge_with_new_price(CORRE, VENCE, "month", 1) == datetime(
        2026, 12, 12, 15, 0, tzinfo=UTC
    )
    # Si corre antes del primer intento, va en ese mismo cobro.
    assert first_charge_with_new_price(PRIMER_INTENTO, VENCE, "month", 1) == PRIMER_INTENTO
    # Plan de dos meses: el siguiente cobro es dos meses despues.
    assert first_charge_with_new_price(CORRE, VENCE, "month", 2) == datetime(
        2027, 1, 12, 15, 0, tzinfo=UTC
    )
