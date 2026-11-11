"""La nota credito (`billing/credit_note.py`): motivo, valor en pesos y texto.
Sin base ni red."""

from datetime import date
from decimal import Decimal

import pytest

from app.billing import fx
from app.billing.credit_note import (
    REASON_ANNULMENT,
    REASON_PARTIAL,
    cop_cents_for,
    observations,
    reason_for,
)
from app.billing.invoice_document import VAT_EXCLUSION_NOTE, FrozenRates

# Las tasas de la factura de 32 EUR de los tests de la emision.
TASAS = fx.Rates(eur_usd=Decimal("1.1165"), usd_cop=Decimal("3228.26"))
PAGADO = 3200
FACTURA_COP = fx.to_cop_cents(PAGADO, "EUR", TASAS)  # 11533927


def _nota(antes: int, monto: int, *, tasas: fx.Rates = TASAS, factura: int = FACTURA_COP) -> int:
    return cop_cents_for(
        credited_before_cents=antes,
        amount_cents=monto,
        paid_cents=PAGADO,
        currency="EUR",
        rates=tasas,
        invoice_cop_cents=factura,
    )


def test_el_motivo_es_2_si_devuelve_todo_y_1_si_una_parte() -> None:
    """La contadora (2026-11-11): total, "2 - Anulacion de factura
    electronica"; parcial, "1 - Devolucion parcial"."""
    assert reason_for(3200, 3200) == REASON_ANNULMENT == 2
    assert reason_for(1000, 3200) == REASON_PARTIAL == 1
    with pytest.raises(ValueError):
        reason_for(3300, 3200)
    with pytest.raises(ValueError):
        reason_for(0, 3200)


def test_el_reembolso_total_vale_lo_mismo_que_la_factura() -> None:
    assert FACTURA_COP == 11533927
    assert _nota(0, PAGADO) == FACTURA_COP


def test_la_factura_manda_aunque_su_redondeo_sea_otro() -> None:
    """Lo pagado entero vale lo que dice la factura, sin volver a convertir."""
    assert _nota(0, PAGADO, factura=FACTURA_COP - 1) == FACTURA_COP - 1


def test_un_parcial_usa_las_tasas_de_la_factura() -> None:
    valor = _nota(0, 1000)
    assert valor == fx.to_cop_cents(1000, "EUR", TASAS) == 3604352
    # Con otras tasas (las del dia del reembolso) daria otro valor: no se usan.
    otras = fx.Rates(eur_usd=Decimal("1.20"), usd_cop=Decimal("4000"))
    assert _nota(0, 1000, tasas=otras) != valor


def test_los_parciales_que_completan_el_total_suman_la_factura_al_centavo() -> None:
    partes = [1000, 1200, 1000]
    antes = 0
    valores = []
    for parte in partes:
        valores.append(_nota(antes, parte))
        antes += parte
    assert sum(valores) == FACTURA_COP
    assert all(v > 0 for v in valores)


def test_los_parciales_nunca_pasan_de_la_factura() -> None:
    for corte in range(1, PAGADO):
        assert _nota(0, corte) + _nota(corte, PAGADO - corte) == FACTURA_COP


def test_no_se_devuelve_mas_de_lo_pagado() -> None:
    with pytest.raises(ValueError):
        _nota(3000, 300)
    with pytest.raises(ValueError):
        _nota(-1, 100)


def test_un_pago_en_pesos_no_se_convierte() -> None:
    assert cop_cents_for(
        credited_before_cents=0, amount_cents=500_000, paid_cents=1_000_000, currency="COP",
        rates=fx.Rates(), invoice_cop_cents=1_000_000,
    ) == 500_000


FROZEN = FrozenRates(
    eur_usd=Decimal("1.1165"),
    eur_usd_date=date(2026, 11, 6),
    eur_usd_source="Banco Central Europeo",
    usd_cop=Decimal("3228.26"),
    usd_cop_date=date(2026, 11, 6),
    usd_cop_source="Superintendencia Financiera",
)


def test_el_texto_dice_que_factura_corrige_y_con_que_tasas() -> None:
    texto = observations(
        invoice_name="FV-2-15", reason=2, amount_cents=3200, currency="EUR",
        cop_cents=FACTURA_COP, rates=FROZEN, payment_reference="SA-123",
        invoice_issue_date=date(2026, 11, 6),
    )
    assert texto.startswith("Nota crédito de la factura FV-2-15 del 06/11/2026, por reembolso total.")
    assert VAT_EXCLUSION_NOTE in texto
    assert "Valor devuelto: 32,00 EUR." in texto
    assert "Tasa EUR/USD del 06/11/2026: 1,1165 (Banco Central Europeo)." in texto
    assert "TRM del 06/11/2026: 3.228,26 COP/USD" in texto
    assert "Valor en pesos: 115.339,27 COP." in texto
    assert texto.endswith("Referencia del pago: SA-123.")

    parcial = observations(
        invoice_name="FV-2-15", reason=1, amount_cents=1000, currency="EUR",
        cop_cents=3604352, rates=FROZEN, payment_reference="SA-123", invoice_issue_date=None,
    )
    assert "por reembolso parcial" in parcial and "Valor devuelto: 10,00 EUR." in parcial


def test_un_pago_en_euros_sin_tasas_no_da_texto() -> None:
    with pytest.raises(ValueError):
        observations(
            invoice_name="FV-2-15", reason=2, amount_cents=3200, currency="EUR",
            cop_cents=FACTURA_COP, rates=None, payment_reference="SA-123",
            invoice_issue_date=None,
        )
