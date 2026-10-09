"""Cotizaciones (docs/PLATAFORMA_COMPLETA.md §3.3). Sin base de datos ni red."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.billing.pricing import (
    MAX_PERCENT,
    CouponKind,
    CouponRejection,
    CouponTerms,
    PlanPrice,
    Quote,
    coupon_rejection,
    percent_discount,
    quote,
)

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)

# El plan unico: 100.000 COP, en centavos.
PLAN = PlanPrice(id="plan-mensual", price_cents=10_000_000, currency="COP")


def coupon(**changes: object) -> CouponTerms:
    base = CouponTerms(
        kind=CouponKind.percent,
        value=20,
        currency=None,
        active=True,
        valid_from=NOW - timedelta(days=1),
        valid_until=None,
        max_redemptions=None,
        redemptions_count=0,
        plan_ids=frozenset(),
        already_used_by_user=False,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def fixed(value: int, currency: str | None = "COP", **changes: object) -> CouponTerms:
    return coupon(kind=CouponKind.fixed_cents, value=value, currency=currency, **changes)


def full_price(rejection: CouponRejection) -> Quote:
    return Quote(
        subtotal_cents=10_000_000,
        discount_cents=0,
        total_cents=10_000_000,
        currency="COP",
        coupon_rejection=rejection,
    )


# ---------- Sin cupon y cupon que aplica ----------


def test_sin_cupon_se_cobra_el_precio_del_plan() -> None:
    assert quote(PLAN, None, NOW) == Quote(
        subtotal_cents=10_000_000,
        discount_cents=0,
        total_cents=10_000_000,
        currency="COP",
        coupon_rejection=None,
    )


def test_cupon_de_porcentaje() -> None:
    assert quote(PLAN, coupon(value=20), NOW) == Quote(
        subtotal_cents=10_000_000,
        discount_cents=2_000_000,
        total_cents=8_000_000,
        currency="COP",
        coupon_rejection=None,
    )


def test_cupon_de_monto_fijo() -> None:
    q = quote(PLAN, fixed(1_500_000), NOW)
    assert (q.discount_cents, q.total_cents, q.coupon_rejection) == (1_500_000, 8_500_000, None)


def test_la_moneda_de_la_cotizacion_es_la_del_plan() -> None:
    usd = PlanPrice(id="otro", price_cents=3_000, currency="USD")
    assert quote(usd, coupon(value=10), NOW).currency == "USD"


# ---------- Redondeo ----------


@pytest.mark.parametrize(
    ("amount", "percent", "expected"),
    [
        (999, 33, 329),  # 329,67 -> 329
        (1, 99, 0),  # 0,99 -> 0
        (199, 50, 99),  # 99,5 -> 99: hacia abajo, no al mas cercano
        (10_000_000, 15, 1_500_000),  # exacto
        (10_000_001, 33, 3_300_000),  # 3.300.000,33 -> 3.300.000
    ],
)
def test_el_porcentaje_redondea_hacia_abajo(amount: int, percent: int, expected: int) -> None:
    assert percent_discount(amount, percent) == expected


def test_la_cotizacion_usa_el_redondeo_hacia_abajo() -> None:
    plan = PlanPrice(id="p", price_cents=999, currency="COP")
    q = quote(plan, coupon(value=33), NOW)
    assert (q.discount_cents, q.total_cents) == (329, 670)


def test_los_montos_son_enteros() -> None:
    q = quote(PlanPrice(id="p", price_cents=999, currency="COP"), coupon(value=33), NOW)
    assert all(type(v) is int for v in (q.subtotal_cents, q.discount_cents, q.total_cents))


def test_subtotal_menos_descuento_es_el_total() -> None:
    for percent in range(1, MAX_PERCENT + 1):
        for price in (1, 7, 999, 10_000_000, 10_000_001):
            q = quote(PlanPrice(id="p", price_cents=price, currency="COP"), coupon(value=percent), NOW)
            assert q.subtotal_cents - q.discount_cents == q.total_cents
            assert q.total_cents > 0


# ---------- Cupon que no aplica: precio completo y el motivo ----------


def test_cupon_inactivo() -> None:
    assert quote(PLAN, coupon(active=False), NOW) == full_price(CouponRejection.inactive)


def test_cupon_vencido() -> None:
    q = quote(PLAN, coupon(valid_until=NOW - timedelta(seconds=1)), NOW)
    assert q == full_price(CouponRejection.expired)


def test_el_vencimiento_es_exclusivo() -> None:
    assert quote(PLAN, coupon(valid_until=NOW), NOW).coupon_rejection is CouponRejection.expired
    vigente = coupon(valid_until=NOW + timedelta(seconds=1))
    assert quote(PLAN, vigente, NOW).coupon_rejection is None


def test_cupon_que_todavia_no_empieza() -> None:
    q = quote(PLAN, coupon(valid_from=NOW + timedelta(seconds=1)), NOW)
    assert q == full_price(CouponRejection.not_started)
    assert quote(PLAN, coupon(valid_from=NOW), NOW).coupon_rejection is None


def test_cupon_agotado() -> None:
    q = quote(PLAN, coupon(max_redemptions=5, redemptions_count=5), NOW)
    assert q == full_price(CouponRejection.exhausted)


def test_cupon_con_cupos() -> None:
    q = quote(PLAN, coupon(max_redemptions=5, redemptions_count=4), NOW)
    assert q.coupon_rejection is None
    assert q.discount_cents == 2_000_000


def test_cupon_de_otro_plan() -> None:
    q = quote(PLAN, coupon(plan_ids=frozenset({"plan-anual"})), NOW)
    assert q == full_price(CouponRejection.other_plan)


def test_cupon_limitado_a_este_plan() -> None:
    q = quote(PLAN, coupon(plan_ids=frozenset({"plan-mensual", "plan-anual"})), NOW)
    assert q.coupon_rejection is None


def test_cupon_de_otra_moneda() -> None:
    assert quote(PLAN, fixed(500, "USD"), NOW) == full_price(CouponRejection.currency_mismatch)


def test_cupon_de_monto_fijo_sin_moneda_no_aplica() -> None:
    assert quote(PLAN, fixed(500, None), NOW).coupon_rejection is CouponRejection.currency_mismatch


def test_el_porcentaje_no_mira_la_moneda() -> None:
    assert quote(PLAN, coupon(currency="USD"), NOW).coupon_rejection is None


def test_cupon_ya_usado_por_el_usuario() -> None:
    q = quote(PLAN, coupon(already_used_by_user=True), NOW)
    assert q == full_price(CouponRejection.already_used)


# ---------- El total nunca llega a cero ----------


def test_monto_fijo_igual_al_precio_no_aplica() -> None:
    assert quote(PLAN, fixed(10_000_000), NOW) == full_price(CouponRejection.covers_total)


def test_monto_fijo_mayor_que_el_precio_no_deja_total_negativo() -> None:
    q = quote(PLAN, fixed(99_000_000), NOW)
    assert q == full_price(CouponRejection.covers_total)


def test_monto_fijo_un_centavo_por_debajo_del_precio_aplica() -> None:
    q = quote(PLAN, fixed(9_999_999), NOW)
    assert (q.total_cents, q.coupon_rejection) == (1, None)


def test_el_porcentaje_maximo_deja_algo_que_cobrar() -> None:
    q = quote(PLAN, coupon(value=MAX_PERCENT), NOW)
    assert (q.discount_cents, q.total_cents) == (9_900_000, 100_000)


def test_un_cupon_del_100_por_ciento_no_se_cotiza() -> None:
    with pytest.raises(ValueError):
        quote(PLAN, coupon(value=100), NOW)


@pytest.mark.parametrize("value", [0, -5])
def test_un_cupon_sin_valor_no_se_cotiza(value: int) -> None:
    with pytest.raises(ValueError):
        quote(PLAN, coupon(value=value), NOW)


@pytest.mark.parametrize("price", [0, -1])
def test_un_plan_sin_precio_no_se_cotiza(price: int) -> None:
    with pytest.raises(ValueError):
        quote(PlanPrice(id="p", price_cents=price, currency="COP"), None, NOW)


# ---------- Orden de los motivos ----------


def test_con_varios_motivos_gana_el_del_cupon() -> None:
    # Apagado, vencido, agotado, de otro plan y ya usado: se dice que esta apagado.
    c = coupon(
        active=False,
        valid_until=NOW - timedelta(days=1),
        max_redemptions=1,
        redemptions_count=1,
        plan_ids=frozenset({"otro"}),
        already_used_by_user=True,
    )
    assert coupon_rejection(PLAN, c, NOW) is CouponRejection.inactive
    assert coupon_rejection(PLAN, replace(c, active=True), NOW) is CouponRejection.expired
    c = replace(c, active=True, valid_until=None)
    assert coupon_rejection(PLAN, c, NOW) is CouponRejection.exhausted
    c = replace(c, max_redemptions=None)
    assert coupon_rejection(PLAN, c, NOW) is CouponRejection.other_plan
    c = replace(c, plan_ids=frozenset())
    assert coupon_rejection(PLAN, c, NOW) is CouponRejection.already_used
