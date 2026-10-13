"""Calendario de cobros y precio de la renovacion (§3.5, §3.7 y §3.8). Sin base ni red."""

from datetime import UTC, datetime, timedelta

import pytest

from app.billing.pricing import (
    CouponKind,
    RenewalDiscount,
    periods_remaining_after_renewal,
    renewal_quote,
)
from app.billing.schedule import (
    MAX_ATTEMPTS,
    NOTICE_DAYS,
    attempt_time,
    expiry_notice_due,
    first_charge_at,
    next_attempt,
    renewal_notice_due,
    should_expire,
)

VENCE = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)
H = timedelta(hours=1)
PRECIO = 10_000_000


# ---------- Intentos ----------


def test_tres_intentos_48_24_y_0_horas_antes_del_vencimiento() -> None:
    assert MAX_ATTEMPTS == 3
    assert attempt_time(VENCE, 1) == VENCE - 48 * H
    assert attempt_time(VENCE, 2) == VENCE - 24 * H
    assert attempt_time(VENCE, 3) == VENCE
    assert first_charge_at(VENCE) == VENCE - 48 * H


@pytest.mark.parametrize("intento", [0, 4, -1])
def test_no_existe_un_cuarto_intento(intento: int) -> None:
    with pytest.raises(ValueError):
        attempt_time(VENCE, intento)


@pytest.mark.parametrize(
    ("cuando", "hechos", "toca"),
    [
        # Antes de las 48 h no se cobra.
        (VENCE - 49 * H, 0, None),
        (VENCE - 48 * H - timedelta(seconds=1), 0, None),
        # El primero, justo a las 48 h.
        (VENCE - 48 * H, 0, 1),
        (VENCE - 30 * H, 0, 1),
        # Ya se hizo el primero: el segundo espera a las 24 h.
        (VENCE - 30 * H, 1, None),
        (VENCE - 24 * H, 1, 2),
        # El tercero, al vencimiento.
        (VENCE - H, 2, None),
        (VENCE, 2, 3),
        # Hechos los tres, no hay mas.
        (VENCE + H, 3, None),
        (VENCE + 100 * H, 3, None),
    ],
)
def test_que_intento_toca(cuando: datetime, hechos: int, toca: int | None) -> None:
    assert next_attempt(cuando, VENCE, hechos) == toca


def test_si_el_job_estuvo_caido_los_intentos_van_de_a_uno_y_en_orden() -> None:
    """Pasado el vencimiento sin ningun intento: el 1, luego el 2, luego el 3."""
    tarde = VENCE + 5 * H
    assert next_attempt(tarde, VENCE, 0) == 1
    assert next_attempt(tarde, VENCE, 1) == 2
    assert next_attempt(tarde, VENCE, 2) == 3
    assert next_attempt(tarde, VENCE, 3) is None


def test_intentos_hechos_negativos_es_un_error() -> None:
    with pytest.raises(ValueError):
        next_attempt(VENCE, VENCE, -1)


# ---------- Vencimiento ----------


def test_vence_exactamente_en_el_vencimiento_sin_periodo_de_gracia() -> None:
    assert should_expire(VENCE, VENCE, 3, attempt_in_flight=False) is True
    assert should_expire(VENCE - timedelta(seconds=1), VENCE, 3, attempt_in_flight=False) is False


def test_no_vence_con_intentos_por_hacer_ni_con_un_cobro_sin_resolver() -> None:
    assert should_expire(VENCE + H, VENCE, 2, attempt_in_flight=False) is False
    assert should_expire(VENCE + H, VENCE, 3, attempt_in_flight=True) is False


# ---------- Avisos ----------


def test_el_aviso_del_cobro_va_siete_dias_antes_del_primer_intento() -> None:
    assert NOTICE_DAYS == 7
    primer_intento = VENCE - 48 * H
    justo = primer_intento - timedelta(days=7)
    assert renewal_notice_due(justo - timedelta(seconds=1), VENCE) is False
    assert renewal_notice_due(justo, VENCE) is True
    # Y sigue debiendose si el job no corrio ese dia.
    assert renewal_notice_due(primer_intento - H, VENCE) is True


def test_el_aviso_del_pago_manual_va_siete_dias_antes_del_vencimiento() -> None:
    justo = VENCE - timedelta(days=7)
    assert expiry_notice_due(justo - timedelta(seconds=1), VENCE) is False
    assert expiry_notice_due(justo, VENCE) is True
    assert expiry_notice_due(VENCE - H, VENCE) is True
    # Vencido ya no es un aviso de "esta por vencer".
    assert expiry_notice_due(VENCE, VENCE) is False


# ---------- Precio de la renovacion ----------


def _descuento(**campos) -> RenewalDiscount:
    datos = {"kind": CouponKind.percent, "value": 20, "currency": None, "periods_remaining": 2}
    return RenewalDiscount(**{**datos, **campos})


def test_sin_cupon_se_cobra_el_precio_congelado() -> None:
    q = renewal_quote(PRECIO, "COP", None)
    assert (q.subtotal_cents, q.discount_cents, q.total_cents, q.currency) == (PRECIO, 0, PRECIO, "COP")


def test_cupon_repeating_descuenta_mientras_queden_periodos() -> None:
    q = renewal_quote(PRECIO, "COP", _descuento(periods_remaining=2))
    assert (q.discount_cents, q.total_cents) == (2_000_000, 8_000_000)
    q = renewal_quote(PRECIO, "COP", _descuento(periods_remaining=1))
    assert q.total_cents == 8_000_000
    # En cero se cobra el precio congelado completo (§3.5).
    q = renewal_quote(PRECIO, "COP", _descuento(periods_remaining=0))
    assert (q.discount_cents, q.total_cents) == (0, PRECIO)


def test_cupon_forever_descuenta_siempre() -> None:
    q = renewal_quote(PRECIO, "COP", _descuento(periods_remaining=None))
    assert q.total_cents == 8_000_000
    assert periods_remaining_after_renewal(None) is None


def test_cupon_de_monto_fijo_en_la_renovacion() -> None:
    fijo = _descuento(kind=CouponKind.fixed_cents, value=1_500_000, currency="COP")
    assert renewal_quote(PRECIO, "COP", fijo).total_cents == 8_500_000
    # De otra moneda no aplica.
    otra = _descuento(kind=CouponKind.fixed_cents, value=1_500_000, currency="USD")
    assert renewal_quote(PRECIO, "COP", otra).total_cents == PRECIO


def test_un_descuento_nunca_deja_la_renovacion_en_cero() -> None:
    todo = _descuento(kind=CouponKind.fixed_cents, value=PRECIO, currency="COP")
    q = renewal_quote(PRECIO, "COP", todo)
    assert (q.discount_cents, q.total_cents) == (0, PRECIO)


def test_el_porcentaje_redondea_hacia_abajo_tambien_en_la_renovacion() -> None:
    q = renewal_quote(999, "COP", _descuento(value=33))
    assert (q.discount_cents, q.total_cents) == (329, 670)


def test_cada_renovacion_aprobada_gasta_un_periodo_con_descuento() -> None:
    assert periods_remaining_after_renewal(2) == 1
    assert periods_remaining_after_renewal(1) == 0
    assert periods_remaining_after_renewal(0) == 0


def test_un_precio_que_no_es_positivo_es_un_error() -> None:
    with pytest.raises(ValueError):
        renewal_quote(0, "COP", None)
