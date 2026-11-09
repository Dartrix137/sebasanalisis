"""La emision de la factura electronica con Siigo (docs/PLATAFORMA_COMPLETA.md
§3.17, "Paso 5.4"; Fase 5, paso 5.4).

El pago va por Tipster Page sobre su transporte simulado y la factura por el
emisor de Siigo de verdad sobre el suyo (`siigo_sandbox.py`). Datos de clientes
inventados.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text

from app.billing import fx
from app.billing.invoice_document import VAT_EXCLUSION_NOTE, idempotency_key
from app.core.invoices import MAX_ATTEMPTS, run_emission
from app.models import Invoice
from tests.api.siigo_sandbox import DOCUMENTO, FORMA_DE_PAGO, PARTNER, PRODUCTO, VENDEDOR, Falla
from tests.api.test_subscriptions import _abrir_pago, _aprobar, _cuenta, _pagos

# 32 EUR con la TRM 3.228,26 y el EUR/USD 1,1165 de las tasas simuladas.
PESOS = Decimal("115339.27")
CENTAVOS = 11533927


def _factura(db, payment_id) -> Invoice:
    db.expire_all()
    return db.scalar(select(Invoice).where(Invoice.payment_id == payment_id))


def _pago_aprobado(client, db, tipster):
    token, user_id, email = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    _aprobar(client, tipster, pago)
    [pago] = _pagos(db, user_id)
    return pago, email


def _correr(db, siigo, now=None):
    return run_emission(db, siigo.issuer, siigo.tasas, now or datetime.now(UTC))


# ---------- El caso feliz ----------


def test_un_pago_aprobado_sale_facturado_enseguida(client, db, tipster, siigo) -> None:
    pago, email = _pago_aprobado(client, db, tipster)

    factura = _factura(db, pago.id)
    assert factura.status == "accepted" and factura.cufe and factura.accepted_at
    assert factura.provider_name == "FV-4-1"
    # Lo congelado: monto en pesos, tasas con su dia y su fuente, comprador.
    assert factura.cop_cents == CENTAVOS and factura.provider_total == PESOS
    assert factura.usd_cop == Decimal("3228.26") and factura.eur_usd == Decimal("1.1165")
    assert factura.usd_cop_date == factura.operation_date
    assert (factura.buyer_id_type, factura.buyer_id_number, factura.buyer_email) == (
        "13", "1234567890", email
    )
    assert factura.idempotency_key == idempotency_key(factura.id)
    assert factura.issue_date == fx.operation_date(datetime.now(UTC))

    # Lo que le llego a Siigo.
    [crear] = siigo.pedidos_a("POST", "/v1/invoices")
    assert crear.headers["Idempotency-Key"] == factura.idempotency_key
    assert crear.headers["Partner-Id"] == PARTNER
    assert crear.headers["Authorization"].startswith("Bearer ")
    cuerpo = siigo.cuerpo(crear)
    assert cuerpo["document"] == {"id": DOCUMENTO} and cuerpo["seller"] == VENDEDOR
    assert "currency" not in cuerpo  # en pesos
    assert cuerpo["items"] == [{"code": PRODUCTO, "description": factura.description,
                                "quantity": 1, "price": float(PESOS)}]
    assert "taxes" not in cuerpo["items"][0]  # excluida de IVA
    assert cuerpo["payments"] == [{"id": FORMA_DE_PAGO, "value": float(PESOS)}]
    assert cuerpo["stamp"] == {"send": True} and cuerpo["mail"] == {"send": True}
    assert cuerpo["date"] == factura.issue_date.isoformat()
    assert cuerpo["observations"].startswith(VAT_EXCLUSION_NOTE)
    assert "Valor pagado: 32,00 EUR." in cuerpo["observations"]
    assert pago.reference in cuerpo["observations"]

    # El tercero se creo con los datos de facturacion y el correo de la cuenta.
    [cliente] = [siigo.cuerpo(p) for p in siigo.pedidos_a("POST", "/v1/customers")]
    assert cliente["identification"] == "1234567890" and cliente["id_type"] == "13"
    assert cliente["name"] == ["Cliente", "De Prueba"]
    assert cliente["address"]["city"] == {"country_code": "Co", "state_code": "11",
                                          "city_code": "11001"}
    assert cliente["contacts"][0]["email"] == email
    assert cliente["fiscal_responsibilities"] == [{"code": "R-99-PN"}]


def test_el_mismo_cliente_no_se_vuelve_a_crear(client, db, tipster, siigo) -> None:
    token, user_id, _ = _cuenta(client, db)
    for _ in range(2):
        pago = _abrir_pago(client, db, token)
        _aprobar(client, tipster, pago)
    assert len(siigo.pedidos_a("POST", "/v1/customers")) == 1
    assert len(siigo.pedidos_a("POST", "/v1/invoices")) == 2


def test_cambiar_los_datos_despues_no_altera_una_factura_emitida(client, db, tipster, siigo) -> None:
    pago, _ = _pago_aprobado(client, db, tipster)
    db.execute(text("UPDATE billing_profiles SET address = 'Otra 9'"))
    db.commit()
    assert _factura(db, pago.id).buyer_address == "Calle 1 # 2-3"


# ---------- Lo que la hace esperar ----------


def test_sin_tasa_publicada_espera_y_la_emite_una_corrida_posterior(client, db, tipster, siigo) -> None:
    siigo.tasas.publicadas = False
    pago, _ = _pago_aprobado(client, db, tipster)
    factura = _factura(db, pago.id)
    assert factura.status == "pending" and factura.waiting_reason == "rates_pending"
    assert factura.prepared_at is None and siigo.pedidos_a("POST", "/v1/invoices") == []

    siigo.tasas.publicadas = True
    _correr(db, siigo)
    assert _factura(db, pago.id).status == "accepted"


def test_sin_datos_de_facturacion_espera(client, db, tipster, siigo) -> None:
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    db.execute(text("DELETE FROM billing_profiles WHERE user_id = :id"), {"id": user_id})
    db.commit()
    _aprobar(client, tipster, pago)
    factura = _factura(db, pago.id)
    assert factura.status == "pending" and factura.waiting_reason == "billing_profile_missing"


def test_con_la_emision_apagada_la_factura_se_queda_pendiente(client, db, tipster) -> None:
    pago, _ = _pago_aprobado(client, db, tipster)
    factura = _factura(db, pago.id)
    assert factura.status == "pending" and factura.prepared_at is None


# ---------- Errores de Siigo ----------


def test_un_tiempo_agotado_se_reintenta_con_la_misma_llave_y_no_duplica(
    client, db, tipster, siigo
) -> None:
    siigo.fallar("POST", "/v1/invoices", Falla(0, timeout=True))
    pago, _ = _pago_aprobado(client, db, tipster)
    factura = _factura(db, pago.id)
    assert factura.status == "sending" and factura.attempts == 1
    assert factura.next_attempt_at is not None

    _correr(db, siigo, now=factura.next_attempt_at + timedelta(seconds=1))
    factura = _factura(db, pago.id)
    assert factura.status == "accepted" and factura.attempts == 2
    llaves = {p.headers["Idempotency-Key"] for p in siigo.pedidos_a("POST", "/v1/invoices")}
    assert llaves == {factura.idempotency_key} and len(siigo.facturas) == 1


def test_un_limite_corto_se_espera_y_uno_largo_queda_para_despues(
    client, db, tipster, siigo
) -> None:
    siigo.fallar("POST", "/v1/invoices",
                 Falla(429, ["requests_limit"], "Rate limit is exceeded. Try again in 5 seconds."))
    pago, _ = _pago_aprobado(client, db, tipster)
    assert _factura(db, pago.id).status == "accepted"
    assert 6.0 in siigo.dormido  # espero los 5 s y uno mas

    siigo.fallar("POST", "/v1/invoices",
                 Falla(429, ["requests_limit"], "Rate limit is exceeded. Try again in 120 seconds."))
    pago, _ = _pago_aprobado(client, db, tipster)
    factura = _factura(db, pago.id)
    assert factura.status == "pending" and factura.last_error_codes == ["requests_limit"]
    assert factura.next_attempt_at is not None


def test_un_error_de_datos_la_deja_fallida_y_no_se_reintenta_sola(client, db, tipster, siigo) -> None:
    siigo.fallar("POST", "/v1/invoices",
                 Falla(400, ["invalid_total_payments"], "El total de pagos no coincide"))
    pago, _ = _pago_aprobado(client, db, tipster)
    factura = _factura(db, pago.id)
    assert factura.status == "failed" and factura.last_error_codes == ["invalid_total_payments"]

    _correr(db, siigo, now=datetime.now(UTC) + timedelta(days=2))
    assert len(siigo.pedidos_a("POST", "/v1/invoices")) == 1


def test_un_error_de_configuracion_frena_la_corrida(client, db, tipster, siigo) -> None:
    siigo.tasas.publicadas = False  # que las dos queden pendientes
    primero, _ = _pago_aprobado(client, db, tipster)
    segundo, _ = _pago_aprobado(client, db, tipster)
    siigo.tasas.publicadas = True
    siigo.fallar("POST", "/v1/invoices",
                 Falla(400, ["invalid_dian_resolution"], "La resolucion vencio"))

    report = _correr(db, siigo)
    assert report.stopped and report.stopped.startswith("config")
    assert len(siigo.pedidos_a("POST", "/v1/invoices")) == 1  # la segunda ni se intento
    a, b = _factura(db, primero.id), _factura(db, segundo.id)
    assert a.status == "pending" and a.attempts == 0 and a.last_error_codes
    assert b.status == "pending"


def test_un_tipo_de_comprobante_que_no_es_electronico_no_deja_emitir(
    client, db, tipster, siigo
) -> None:
    siigo.tipo_de_comprobante["electronic_type"] = "NoElectronic"
    pago, _ = _pago_aprobado(client, db, tipster)
    assert _factura(db, pago.id).status == "pending"
    assert siigo.pedidos_a("POST", "/v1/invoices") == []


def test_un_total_que_no_cuadra_la_deja_fallida(client, db, tipster, siigo) -> None:
    siigo.total_distinto = Decimal("115339.30")
    pago, _ = _pago_aprobado(client, db, tipster)
    factura = _factura(db, pago.id)
    assert factura.status == "failed" and factura.last_error_codes == ["total_mismatch"]


def test_tras_muchos_intentos_pasajeros_queda_fallida(client, db, tipster, siigo) -> None:
    siigo.tasas.publicadas = False
    pago, _ = _pago_aprobado(client, db, tipster)
    siigo.tasas.publicadas = True
    db.execute(text("UPDATE invoices SET attempts = :n WHERE payment_id = :id"),
               {"n": MAX_ATTEMPTS - 1, "id": pago.id})
    db.commit()
    siigo.fallar("POST", "/v1/invoices", Falla(503, ["service_unavailable"]))
    _correr(db, siigo)
    assert _factura(db, pago.id).status == "failed"


def test_un_token_vencido_se_renueva_una_vez(client, db, tipster, siigo) -> None:
    _pago_aprobado(client, db, tipster)
    siigo.token_valido = "otro"  # Siigo invalido el token que teniamos
    _pago_aprobado(client, db, tipster)
    assert siigo.tokens == 2


# ---------- La DIAN ----------


def test_una_factura_en_borrador_se_confirma_en_otra_corrida(client, db, tipster, siigo) -> None:
    siigo.estado_nuevo = "Draft"
    pago, _ = _pago_aprobado(client, db, tipster)
    assert _factura(db, pago.id).status == "issued"

    siigo.estado_al_consultar = "Accepted"
    _correr(db, siigo)
    factura = _factura(db, pago.id)
    assert factura.status == "accepted" and factura.cufe


def test_una_rechazada_por_la_dian_guarda_sus_motivos(client, db, tipster, siigo) -> None:
    siigo.estado_nuevo = "Draft"
    pago, _ = _pago_aprobado(client, db, tipster)
    siigo.estado_al_consultar = "Rejected"
    _correr(db, siigo)
    factura = _factura(db, pago.id)
    assert factura.status == "rejected"
    assert factura.dian_errors == ["Regla FAD06: el NIT del emisor no coincide"]


# ---------- Privacidad ----------


def test_el_documento_del_comprador_no_va_al_log(client, db, tipster, siigo, caplog) -> None:
    siigo.fallar("POST", "/v1/invoices",
                 Falla(400, ["invalid_identification"], "La identificacion 1234567890 no vale"))
    _pago_aprobado(client, db, tipster)
    assert "invalid_identification" in caplog.text
    assert "1234567890" not in caplog.text


def test_la_fecha_es_la_del_envio_y_la_trm_la_del_pago(client, db, tipster, siigo) -> None:
    siigo.tasas.publicadas = False
    pago, _ = _pago_aprobado(client, db, tipster)
    siigo.tasas.publicadas = True
    manana = datetime.now(UTC) + timedelta(days=1)
    _correr(db, siigo, now=manana)
    factura = _factura(db, pago.id)
    assert factura.issue_date == fx.operation_date(manana)
    assert factura.usd_cop_date == factura.operation_date
    assert factura.issue_date > factura.operation_date or factura.issue_date == date.today()


def test_un_comprobante_con_centro_de_costo_lo_pide_en_la_configuracion(
    client, db, tipster, siigo
) -> None:
    """Probado en la empresa de pruebas el 2026-11-09: sin el centro de costo,
    un tipo que lo maneja responde `documents_service`."""
    siigo.tipo_de_comprobante["cost_center"] = True
    pago, _ = _pago_aprobado(client, db, tipster)
    assert _factura(db, pago.id).status == "pending"
    assert siigo.pedidos_a("POST", "/v1/invoices") == []

    siigo.issuer.cost_center_id = 1028
    siigo.issuer._ready_until = 0
    _correr(db, siigo)
    assert _factura(db, pago.id).status == "accepted"
    [crear] = siigo.pedidos_a("POST", "/v1/invoices")
    assert siigo.cuerpo(crear)["cost_center"] == 1028
