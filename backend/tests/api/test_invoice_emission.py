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
from tests.api.siigo_sandbox import (
    DOCUMENTO,
    FORMA_DE_PAGO,
    IVA_0,
    IVA_19,
    PARTNER,
    PRODUCTO,
    VENDEDOR,
    Falla,
)
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


def test_con_siigo_tax_id_el_item_lleva_el_iva_del_0(client, db, tipster, siigo) -> None:
    """Soporte de Siigo (2026-11-09): para que la factura muestre el IVA del 0 %
    se informa `taxes` con el id del impuesto. El total no cambia."""
    siigo.issuer.tax_id = IVA_0
    pago, _ = _pago_aprobado(client, db, tipster)
    factura = _factura(db, pago.id)
    assert factura.status == "accepted" and factura.provider_total == PESOS
    [crear] = siigo.pedidos_a("POST", "/v1/invoices")
    item = siigo.cuerpo(crear)["items"][0]
    assert item["taxes"] == [{"id": IVA_0}] and item["price"] == float(PESOS)
    assert siigo.pedidos_a("GET", "/v1/taxes")


def test_un_impuesto_que_no_es_iva_del_0_no_deja_emitir(client, db, tipster, siigo) -> None:
    siigo.issuer.tax_id = IVA_19
    pago, _ = _pago_aprobado(client, db, tipster)
    assert _factura(db, pago.id).status == "pending"
    assert siigo.pedidos_a("POST", "/v1/invoices") == []

    siigo.impuestos[1]["active"] = False
    siigo.issuer.tax_id = IVA_0
    siigo.issuer._ready_until = 0
    report = _correr(db, siigo)
    assert report.stopped and "SIIGO_TAX_ID" in report.stopped
    assert siigo.pedidos_a("POST", "/v1/invoices") == []


def test_el_mismo_cliente_no_se_vuelve_a_crear(client, db, tipster, siigo) -> None:
    token, user_id, _ = _cuenta(client, db)
    for _ in range(2):
        pago = _abrir_pago(client, db, token)
        _aprobar(client, tipster, pago)
    assert len(siigo.pedidos_a("POST", "/v1/customers")) == 1
    assert len(siigo.pedidos_a("POST", "/v1/invoices")) == 2


def _otro_comprador(db, user_id) -> None:
    """Datos de facturacion con el mismo documento que los de `_cuenta`, de otra persona."""
    db.execute(
        text("UPDATE billing_profiles SET first_names = 'Otra', last_names = 'Persona'"
             " WHERE user_id = :id"),
        {"id": user_id},
    )
    db.commit()


def _pago_aprobado_de(client, db, tipster, *, otro_comprador: bool):
    token, user_id, email = _cuenta(client, db)
    if otro_comprador:
        _otro_comprador(db, user_id)
    pago = _abrir_pago(client, db, token)
    _aprobar(client, tipster, pago)
    [pago] = _pagos(db, user_id)
    return pago, email


def test_un_cliente_de_siigo_de_otra_persona_aparta_la_factura(
    client, db, tipster, siigo, caplog
) -> None:
    """Auditoria del 2026-11-12, decidido por el usuario: Siigo reutiliza el
    tercero por el numero de documento. Si el que ya existe tiene otro nombre o
    correo, la factura no se emite a nombre de otro: queda fallida para el admin."""
    primero, _ = _pago_aprobado(client, db, tipster)
    segundo, _ = _pago_aprobado_de(client, db, tipster, otro_comprador=True)

    assert _factura(db, primero.id).status == "accepted"
    factura = _factura(db, segundo.id)
    assert factura.status == "failed"
    assert factura.last_error_codes == ["customer_mismatch"]
    assert "Siigo Nube" in factura.last_error_message
    assert "1234567890" not in factura.last_error_message
    assert "1234567890" not in caplog.text
    assert len(siigo.pedidos_a("POST", "/v1/invoices")) == 1
    assert len(siigo.pedidos_a("POST", "/v1/customers")) == 1


def test_el_mismo_nombre_con_otro_correo_tambien_se_aparta(client, db, tipster, siigo) -> None:
    """El correo del tercero es a donde Siigo manda la factura."""
    _pago_aprobado(client, db, tipster)
    segundo, _ = _pago_aprobado_de(client, db, tipster, otro_comprador=False)
    factura = _factura(db, segundo.id)
    assert (factura.status, factura.last_error_codes) == ("failed", ["customer_mismatch"])


def test_corregido_el_cliente_en_siigo_nube_el_reintento_la_emite(
    client, db, tipster, siigo, admin_token
) -> None:
    _pago_aprobado(client, db, tipster)
    segundo, email = _pago_aprobado_de(client, db, tipster, otro_comprador=True)
    assert _factura(db, segundo.id).status == "failed"

    # El admin revisa y corrige el tercero en Siigo Nube.
    tercero = siigo.clientes["1234567890"]
    tercero["name"] = ["Otra", "Persona"]
    tercero["contacts"] = [{"first_name": "Otra", "last_name": "Persona", "email": email}]
    r = _accion(client, admin_token, segundo, "retry")
    assert r.status_code == 200, r.text
    assert r.json()["invoice"]["status"] == "accepted"


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
    # Los dos pagos de la misma cuenta: la cedula de `_cuenta` es la misma para
    # todas, y una cuenta distinta apartaria la factura por otro motivo.
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    _aprobar(client, tipster, pago)
    assert _factura(db, pago.id).status == "accepted"
    assert 6.0 in siigo.dormido  # espero los 5 s y uno mas

    siigo.fallar("POST", "/v1/invoices",
                 Falla(429, ["requests_limit"], "Rate limit is exceeded. Try again in 120 seconds."))
    pago = _abrir_pago(client, db, token)
    _aprobar(client, tipster, pago)
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


def test_documents_service_frena_la_corrida(client, db, tipster, siigo) -> None:
    """Soporte de Siigo (2026-11-09): sale de la configuracion del tipo de
    comprobante (centro de costo inactivo, cuentas contables), no de la factura."""
    siigo.fallar("POST", "/v1/invoices",
                 Falla(400, ["documents_service"], "Your request could not be completed"))
    pago, _ = _pago_aprobado(client, db, tipster)
    factura = _factura(db, pago.id)
    assert factura.status == "pending" and factura.attempts == 0
    assert factura.last_error_codes == ["documents_service"]


def test_una_ciudad_que_siigo_no_reconoce_deja_fallida_solo_esa_factura(
    client, db, tipster, siigo
) -> None:
    """`invalid_reference` al crear el tercero es de los datos de ese comprador
    (una ciudad que Siigo no reconoce, probado el 2026-11-10): no frena la corrida."""
    siigo.tasas.publicadas = False  # que las dos queden pendientes
    primero, _ = _pago_aprobado(client, db, tipster)
    segundo, _ = _pago_aprobado(client, db, tipster)
    siigo.tasas.publicadas = True
    siigo.fallar("POST", "/v1/customers", Falla(400, ["invalid_reference"], "City not found"))

    report = _correr(db, siigo)
    assert report.stopped is None
    a, b = _factura(db, primero.id), _factura(db, segundo.id)
    assert a.status == "failed" and a.last_error_codes == ["invalid_reference"]
    assert b.status == "accepted"
    assert len(siigo.pedidos_a("POST", "/v1/invoices")) == 1

    _correr(db, siigo, now=datetime.now(UTC) + timedelta(days=2))
    assert _factura(db, primero.id).status == "failed"  # no se reintenta sola


def test_invalid_reference_en_la_factura_sigue_frenando(client, db, tipster, siigo) -> None:
    """En la factura, `invalid_reference` es de la cuenta (comprobante, forma de
    pago, vendedor, impuesto): se repetiria en todas."""
    siigo.fallar("POST", "/v1/invoices",
                 Falla(400, ["invalid_reference"], "Payment type not found"))
    pago, _ = _pago_aprobado(client, db, tipster)
    factura = _factura(db, pago.id)
    assert factura.status == "pending" and factura.attempts == 0
    assert factura.last_error_codes == ["invalid_reference"]


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


def test_una_factura_enviandose_a_la_dian_se_confirma_en_otra_corrida(
    client, db, tipster, siigo
) -> None:
    """`Sending` es el estado que devolvio la empresa de pruebas al crearla
    (2026-11-09); soporte da Draft, Sending, Rejected y Accepted."""
    siigo.estado_nuevo = "Sending"
    pago, _ = _pago_aprobado(client, db, tipster)
    assert _factura(db, pago.id).status == "issued"

    siigo.estado_al_consultar = "Accepted"
    _correr(db, siigo)
    assert _factura(db, pago.id).status == "accepted"


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


# ---------- El admin (§3.17, "Paso 5.4", punto 13) ----------

MOTIVO = "El cliente corrigió su documento"


def _detalle(client, admin_token, pago):
    from tests.api.conftest import auth

    r = client.get(f"/admin/payments/{pago.id}", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    return r.json()


def _accion(client, admin_token, pago, accion: str, motivo: str = MOTIVO):
    from tests.api.conftest import auth

    return client.post(
        f"/admin/payments/{pago.id}/invoice/{accion}", json={"reason": motivo},
        headers=auth(admin_token),
    )


def test_el_admin_ve_la_factura_emitida_con_sus_tasas(client, db, tipster, siigo, admin_token) -> None:
    pago, _ = _pago_aprobado(client, db, tipster)
    detalle = _detalle(client, admin_token, pago)
    factura = detalle["invoice"]
    assert detalle["invoice_issuer_enabled"] is True
    assert factura["status"] == "accepted" and factura["provider_name"] == "FV-4-1"
    assert factura["cufe"] and factura["cop_cents"] == CENTAVOS
    assert (factura["usd_cop"], factura["eur_usd"]) == ("3228.26", "1.1165")
    assert factura["buyer_name"] == "Cliente De Prueba" and factura["buyer_id_number"] == "1234567890"
    lista = client.get("/admin/payments", headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert next(p for p in lista["items"] if p["id"] == str(pago.id))["invoice_status"] == "accepted"


def test_reintentar_una_fallida_toma_los_datos_corregidos(client, db, tipster, siigo, admin_token) -> None:
    siigo.fallar("POST", "/v1/invoices",
                 Falla(400, ["invalid_identification"], "La identificacion no vale"))
    pago, _ = _pago_aprobado(client, db, tipster)
    assert _factura(db, pago.id).status == "failed"

    db.execute(text("UPDATE billing_profiles SET id_number = '9876543210' WHERE user_id = :id"),
               {"id": pago.user_id})
    db.commit()
    r = _accion(client, admin_token, pago, "retry")
    assert r.status_code == 200, r.text
    factura = r.json()["invoice"]
    assert factura["status"] == "accepted" and factura["buyer_id_number"] == "9876543210"
    [fila] = [a for a in r.json()["audit"] if a["action"] == "invoice.retry"]
    assert fila["reason"] == MOTIVO and fila["before"]["status"] == "failed"
    # Sale con otra llave: una llave usada queda usada en Siigo (soporte, 2026-11-09).
    primero, segundo = siigo.pedidos_a("POST", "/v1/invoices")
    assert primero.headers["Idempotency-Key"] != segundo.headers["Idempotency-Key"]
    assert segundo.headers["Idempotency-Key"] == fila["after"]["idempotency_key"]
    assert len(segundo.headers["Idempotency-Key"]) <= 30


def test_reintentar_un_total_que_no_cuadro_crea_otra_si_no_tiene_cufe(
    client, db, tipster, siigo, admin_token
) -> None:
    siigo.estado_nuevo = "Draft"
    siigo.total_distinto = Decimal("115339.30")
    pago, _ = _pago_aprobado(client, db, tipster)
    mala = _factura(db, pago.id)
    assert mala.status == "failed" and mala.provider_name == "FV-4-1" and not mala.cufe

    siigo.total_distinto = None
    siigo.estado_nuevo = "Accepted"
    r = _accion(client, admin_token, pago, "retry", "Anulada en Siigo Nube la FV-4-1")
    assert r.status_code == 200, r.text
    assert r.json()["invoice"]["status"] == "accepted"
    assert r.json()["invoice"]["provider_name"] == "FV-4-2"
    [fila] = [a for a in r.json()["audit"] if a["action"] == "invoice.retry"]
    assert fila["before"]["provider_name"] == "FV-4-1"


def test_un_total_que_no_cuadro_con_cufe_no_se_reintenta(
    client, db, tipster, siigo, admin_token
) -> None:
    siigo.total_distinto = Decimal("115339.30")
    pago, _ = _pago_aprobado(client, db, tipster)
    assert _factura(db, pago.id).cufe
    r = _accion(client, admin_token, pago, "retry")
    assert r.status_code == 409 and "nota credito" in r.json()["detail"]
    assert len(siigo.pedidos_a("POST", "/v1/invoices")) == 1


def test_una_aceptada_no_se_reintenta_y_sin_motivo_no_hay_accion(
    client, db, tipster, siigo, admin_token
) -> None:
    pago, _ = _pago_aprobado(client, db, tipster)
    assert _accion(client, admin_token, pago, "retry").status_code == 409
    assert _accion(client, admin_token, pago, "refresh").status_code == 409
    assert _accion(client, admin_token, pago, "retry", motivo="").status_code == 422


def test_reconsultar_una_rechazada_corregida_en_siigo_nube(client, db, tipster, siigo, admin_token) -> None:
    siigo.estado_nuevo = "Draft"
    pago, _ = _pago_aprobado(client, db, tipster)
    siigo.estado_al_consultar = "Rejected"
    _correr(db, siigo)
    assert _factura(db, pago.id).status == "rejected"

    siigo.estado_al_consultar = "Accepted"  # la corrigieron y reenviaron desde Siigo Nube
    r = _accion(client, admin_token, pago, "refresh")
    assert r.status_code == 200, r.text
    assert r.json()["invoice"]["status"] == "accepted"
    [fila] = [a for a in r.json()["audit"] if a["action"] == "invoice.refresh"]
    assert fila["before"]["status"] == "rejected" and fila["after"]["status"] == "accepted"


def test_con_la_emision_apagada_las_acciones_responden_503(client, db, tipster, admin_token) -> None:
    pago, _ = _pago_aprobado(client, db, tipster)
    assert _detalle(client, admin_token, pago)["invoice_issuer_enabled"] is False
    assert _accion(client, admin_token, pago, "retry").status_code == 503
