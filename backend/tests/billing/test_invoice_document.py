"""El contenido de la factura (`billing/invoice_document.py`). Sin base ni red."""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.billing.invoice_document import (
    IDEMPOTENCY_KEY_LENGTH,
    VAT_EXCLUSION_NOTE,
    FrozenRates,
    classify,
    idempotency_key,
    observations,
    pesos,
)

TASAS = FrozenRates(
    eur_usd=Decimal("1.1165000000"),
    eur_usd_date=date(2026, 11, 6),
    eur_usd_source="Banco Central Europeo",
    usd_cop=Decimal("3228.2600000000"),
    usd_cop_date=date(2026, 11, 6),
    usd_cop_source="Superintendencia Financiera",
)


def test_la_llave_es_alfanumerica_de_25_y_siempre_la_misma() -> None:
    factura = uuid.UUID("0b6f3c1e-2a4d-4e8f-9c7b-5d1a2e3f4a5b")
    llave = idempotency_key(factura)
    assert len(llave) == IDEMPOTENCY_KEY_LENGTH and llave.isalnum()
    assert llave == idempotency_key(factura)
    assert idempotency_key(uuid.UUID(int=0)) == "0" * 25
    assert len(idempotency_key(uuid.UUID(int=2**128 - 1))) == 25


def test_la_llave_de_la_nota_credito_no_choca_con_la_de_su_factura() -> None:
    factura = uuid.uuid4()
    nota = idempotency_key(factura, "NC")
    assert nota != idempotency_key(factura) and len(nota) == 25 and nota.isalnum()


def test_los_centavos_pasan_a_pesos_con_dos_decimales() -> None:
    assert pesos(11533927) == Decimal("115339.27")
    assert pesos(100) == Decimal("1.00")
    for malo in (0, -5, 1.5, True):
        with pytest.raises(ValueError):
            pesos(malo)  # type: ignore[arg-type]


def test_las_observaciones_de_un_pago_en_euros() -> None:
    texto = observations(
        paid_cents=3200, paid_currency="EUR", cop_cents=11533927, rates=TASAS,
        payment_reference="SA-7e00cade",
    )
    assert texto == (
        f"{VAT_EXCLUSION_NOTE} Valor pagado: 32,00 EUR."
        " Tasa EUR/USD del 06/11/2026: 1,1165 (Banco Central Europeo)."
        " TRM del 06/11/2026: 3.228,26 COP/USD (Superintendencia Financiera)."
        " Valor en pesos: 115.339,27 COP. Referencia del pago: SA-7e00cade."
    )


def test_un_pago_en_pesos_solo_lleva_la_exclusion_y_la_referencia() -> None:
    texto = observations(
        paid_cents=10000000, paid_currency="COP", cop_cents=10000000, rates=None,
        payment_reference="SA-1",
    )
    assert texto == f"{VAT_EXCLUSION_NOTE} Referencia del pago: SA-1."


def test_un_pago_en_euros_sin_tasas_es_un_error() -> None:
    with pytest.raises(ValueError):
        observations(paid_cents=3200, paid_currency="EUR", cop_cents=1, rates=None,
                     payment_reference="x")


@pytest.mark.parametrize(
    ("status", "codes", "esperado"),
    [
        (429, ["requests_limit"], "transient"),
        (500, [], "transient"),
        (503, ["service_unavailable"], "transient"),
        # Soporte de Siigo (2026-11-09): es de la configuracion del comprobante.
        (400, ["documents_service"], "config"),
        (500, ["documents_service"], "config"),
        (503, ["service_unavailable", "document_settings"], "config"),
        (429, ["requests_limit", "document_settings"], "transient"),
        (401, ["unauthorized"], "config"),
        (400, ["invalid_dian_resolution"], "config"),
        (400, ["document_settings", "invalid_total_payments"], "config"),
        (400, ["invalid_total_payments"], "invalid"),
        (400, ["parameter_required"], "invalid"),
        (400, [], "invalid"),
    ],
)
def test_como_se_clasifica_un_error_de_siigo(status: int, codes: list[str], esperado: str) -> None:
    assert classify(status, codes) == esperado
