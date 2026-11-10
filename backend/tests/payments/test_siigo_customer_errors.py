"""Errores al crear el tercero en Siigo (docs/PLATAFORMA_COMPLETA.md §3.17,
"Lo decidido por el usuario sobre estas respuestas", ciudades). Sin base de
datos: el emisor de verdad sobre el Siigo simulado de `tests/api/siigo_sandbox.py`.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.invoicing.base import Buyer, InvoiceDraft, IssuerMisconfigured, IssuerRejected
from tests.api.siigo_sandbox import Falla, SiigoSandbox


def _borrador() -> InvoiceDraft:
    return InvoiceDraft(
        idempotency_key="0" * 25,
        issue_date=date(2026, 11, 10),
        buyer=Buyer(
            id_type="42",
            id_number="X1234567",
            first_names="Ana",
            last_names="Prueba",
            email="ana@example.com",
            address="1 Test Street",
            country_code="Us",
            state_code="32",
            city_code="3298",
        ),
        description="Suscripción",
        amount=Decimal("115339.27"),
        observations="Prueba",
    )


def test_una_ciudad_que_siigo_no_reconoce_es_un_error_de_esa_factura() -> None:
    siigo = SiigoSandbox()
    siigo.fallar("POST", "/v1/customers", Falla(400, ["invalid_reference"], "City not found"))

    with pytest.raises(IssuerRejected) as exc:
        siigo.issuer.issue(_borrador())

    assert exc.value.codes == ["invalid_reference"]
    assert siigo.pedidos_a("POST", "/v1/invoices") == []


def test_con_otro_codigo_de_configuracion_al_crear_el_tercero_sigue_frenando() -> None:
    siigo = SiigoSandbox()
    siigo.fallar(
        "POST", "/v1/customers",
        Falla(400, ["invalid_reference", "parameter_inactive"], "Parameter inactive"),
    )

    with pytest.raises(IssuerMisconfigured):
        siigo.issuer.issue(_borrador())


def test_invalid_reference_en_la_factura_sigue_siendo_de_configuracion() -> None:
    siigo = SiigoSandbox()
    siigo.fallar("POST", "/v1/invoices", Falla(400, ["invalid_reference"], "Payment type"))

    with pytest.raises(IssuerMisconfigured):
        siigo.issuer.issue(_borrador())
