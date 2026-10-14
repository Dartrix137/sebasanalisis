"""Cuando aplica el traslado de un precio (§4.10). Sin base ni red."""

from datetime import UTC, datetime, timedelta

import pytest

from app.billing.price_change import (
    INCREASE_NOTICE_DAYS,
    Direction,
    PendingChange,
    direction,
    effective_at,
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
