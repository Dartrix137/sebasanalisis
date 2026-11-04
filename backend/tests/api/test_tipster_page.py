"""Tipster Page por la API: lo nuevo del paso 5.3 de la Fase 5.

Con el proveedor de verdad sobre el transporte simulado (`tipster_sandbox.py`):

- la firma del aviso sobre el `amount` crudo (`12.5` contra `12.50`);
- el `error` que pasa a `paid`, el `fraud`, y un monto o un plan que no coinciden;
- la idempotencia por (pasarela, id de evento);
- el catalogo de medios, y la validacion del medio, el pais y los datos;
- la pagina de pago de un solo uso y su CSP;
- que los datos del comprador viajan a la pasarela y no se guardan;
- la reconsulta de los pagos pendientes en el job de cada hora.
"""

import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, text

from app.core import checkout_pages
from app.core.config import get_settings
from app.core.email import FakeEmailSender
from app.core.renewals import run_renewals
from app.core.subscriptions import CHECKOUT_FAILED
from app.models import Payment, PaymentEvent
from tests.api.conftest import auth
from tests.api.test_billing import _cupon, _mensual
from tests.api.test_subscriptions import (
    PRECIO,
    _abrir_pago,
    _aprobar,
    _cuenta,
    _pagos,
    _suscribir,
    _suscripciones,
    _tiene_acceso,
    _webhook,
)
from tests.api.tipster_sandbox import TipsterSandbox, firma_de_aviso


def _pago_de(client, db, tipster: TipsterSandbox, total_cents: int) -> tuple[str, Payment]:
    """Un pago abierto por `total_cents`, con un cupon de monto fijo."""
    token, _, _ = _cuenta(client, db)
    cupon = _cupon(db, kind="fixed_cents", value=PRECIO - total_cents, currency="EUR")
    return token, _abrir_pago(client, db, token, codigo=cupon.code)


# ---------- El monto crudo del aviso (manual V2 §9.1) ----------


def test_el_aviso_se_firma_sobre_el_monto_como_llega(client, db, tipster) -> None:
    """12,50 EUR: la pasarela lo serializa `12.5` y firma `12.5`."""
    token, pago = _pago_de(client, db, tipster, 1_250)
    assert tipster.pedidos[0]["amount"] == "12.50"
    tipster.pagar(pago, "paid")
    r = _webhook(client, tipster.aviso(pago, "ok", amount="12.5"))
    assert r.json() == {"status": "processed"}
    assert _tiene_acceso(client, token)


def test_un_aviso_firmado_sobre_otro_texto_del_monto_se_rechaza(client, db, tipster) -> None:
    """Firmado sobre `12.5` pero con `12.50` en el cuerpo: si se reformateara el
    numero antes de firmar, pasaria. No pasa: se firma el texto que llego."""
    token, pago = _pago_de(client, db, tipster, 1_250)
    tipster.pagar(pago, "paid")
    firma = firma_de_aviso("ok", pago.reference, "12.5")
    r = _webhook(client, tipster.aviso(pago, "ok", amount="12.50", firma=firma))
    assert r.status_code == 401
    assert not _tiene_acceso(client, token)

    # Y al reves: firmado sobre `12.50` tal como va en el cuerpo, si pasa.
    firma = firma_de_aviso("ok", pago.reference, "12.50")
    assert _webhook(client, tipster.aviso(pago, "ok", amount="12.50", firma=firma)).status_code == 200
    assert _tiene_acceso(client, token)


def test_un_monto_entero_se_firma_sin_decimales(client, db, tipster) -> None:
    """32 EUR: `String(32)` es `32`, no `32.00`."""
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tipster.pagar(pago, "paid")
    mal = firma_de_aviso("ok", pago.reference, "32.00")
    assert _webhook(client, tipster.aviso(pago, "ok", firma=mal)).status_code == 401
    assert _webhook(client, tipster.aviso(pago, "ok")).status_code == 200


def test_la_reconsulta_lee_el_monto_sin_float(client, db, tipster) -> None:
    """`12.5` en la reconsulta son 1250 centavos exactos."""
    token, pago = _pago_de(client, db, tipster, 1_250)
    tipster.pagar(pago, "paid", amount_texto="12.5")
    assert _webhook(client, tipster.aviso(pago, "ok", amount="12.5")).status_code == 200
    assert _pagos(db, str(pago.user_id))[0].status == "approved"


def test_un_monto_con_mas_de_dos_decimales_no_concede_nada(client, db, tipster) -> None:
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tipster.pagar(pago, "paid", amount_texto="32.001")
    assert _webhook(client, tipster.aviso(pago, "ok")).status_code == 200
    [pago] = _pagos(db, str(pago.user_id))
    assert pago.status == "error" and "ilegible" in pago.failure_reason
    assert not _tiene_acceso(client, token)


# ---------- Estados ----------


def test_un_error_que_pasa_a_paid_concede_el_periodo(client, db, tipster, outbox) -> None:
    """Manual V2 §10: un `error` puede pasar a `paid` si el comprador reintenta."""
    token, user_id, correo = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tipster.pagar(pago, "error")
    assert _webhook(client, tipster.aviso(pago, "ko")).status_code == 200
    assert _pagos(db, user_id)[0].status == "declined"
    assert not _tiene_acceso(client, token)

    # Reintenta en la misma pagina del procesador y paga.
    tipster.pagar(pago, "paid")
    assert _webhook(client, tipster.aviso(pago, "ok")).json() == {"status": "processed"}
    [pago] = _pagos(db, user_id)
    assert (pago.status, pago.failure_reason) == ("approved", None)
    assert pago.period_end is not None
    assert _tiene_acceso(client, token)
    assert "Recibo de tu pago en Sebasanálisis" in [m.subject for m in outbox if m.to == correo]


def test_un_rechazo_que_pasa_a_paid_se_ve_al_volver_a_la_pantalla(client, db, tipster) -> None:
    """Si el aviso `ok` no ha llegado, la consulta del pago reconsulta tambien
    un pago rechazado: con Tipster Page puede haber pasado a pagado."""
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tipster.pagar(pago, "error")
    _webhook(client, tipster.aviso(pago, "ko"))
    tipster.pagar(pago, "paid")
    r = client.get(f"/billing/payments/{pago.id}", headers=auth(token))
    assert r.json()["status"] == "approved"
    assert _tiene_acceso(client, token)


def test_un_rechazo_no_se_vuelve_a_rechazar(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tipster.pagar(pago, "error")
    _webhook(client, tipster.aviso(pago, "ko"))
    resuelto = _pagos(db, user_id)[0].resolved_at
    tipster.pagar(pago, "expired")
    assert client.get(f"/billing/payments/{pago.id}", headers=auth(token)).json()["status"] == "declined"
    [pago] = _pagos(db, user_id)
    assert (pago.resolved_at, pago.failure_reason) == (resuelto, "Tipster Page: error")


def test_fraud_no_concede_nada_y_no_se_reabre(client, db, tipster) -> None:
    """`fraud` es terminal (OpenAPI, `PaidOrderStatus`): queda en `error`."""
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tipster.pagar(pago, "fraud")
    assert _webhook(client, tipster.aviso(pago, "ko")).status_code == 200
    [guardado] = _pagos(db, user_id)
    assert (guardado.status, guardado.failure_reason) == ("error", "Tipster Page: fraud")
    # Aunque despues algo dijera `paid`, un pago en error con su orden no se reabre.
    tipster.pagar(pago, "paid")
    _webhook(client, tipster.aviso(pago, "ok"))
    assert _pagos(db, user_id)[0].status == "error"
    assert not _tiene_acceso(client, token)


def test_pagado_por_otro_producto_no_concede_nada(client, db, tipster) -> None:
    """La reconsulta compara el plan (`product_id` = `plans.code`)."""
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tipster.pagar(pago, "paid", product_id="bimestral")
    assert _webhook(client, tipster.aviso(pago, "ok")).status_code == 200
    [pago] = _pagos(db, user_id)
    assert pago.status == "error" and "bimestral" in pago.failure_reason
    assert _suscripciones(db, user_id)[0].status == "pending"
    assert not _tiene_acceso(client, token)


# ---------- Idempotencia por (pasarela, evento) ----------


def test_el_mismo_id_de_evento_de_otra_pasarela_no_bloquea_el_aviso(client, db, tipster) -> None:
    """Decidido el 2026-11-03: la idempotencia va con la pasarela."""
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    db.add(
        PaymentEvent(
            provider="otra-pasarela",
            provider_event_id=f"tipsterpage:{pago.reference}:ok",
            status="ok",
            signature_verified=True,
            processed_at=datetime.now(UTC),
        )
    )
    db.commit()
    tipster.pagar(pago, "paid")
    assert _webhook(client, tipster.aviso(pago, "ok")).json() == {"status": "processed"}
    assert _tiene_acceso(client, token)
    filas = list(
        db.scalars(
            select(PaymentEvent.provider).where(
                PaymentEvent.provider_event_id == f"tipsterpage:{pago.reference}:ok"
            )
        )
    )
    assert sorted(filas) == ["otra-pasarela", "tipsterpage"]


# ---------- El catalogo de medios ----------


def test_el_catalogo_exige_sesion_y_dice_que_pedir(client, db, tipster) -> None:
    assert client.get("/billing/payment-methods").status_code == 401
    token, _, _ = _cuenta(client, db)
    r = client.get("/billing/payment-methods", params={"country": "CO"}, headers=auth(token))
    assert r.status_code == 200, r.text
    assert [(m["key"], m["fields"], m["min_cents"], m["max_cents"], m["currency"]) for m in r.json()] == [
        ("cardtpv", [], 100, 40_000, "EUR"),
        ("ebanxpsecolombia", ["first_name"], 100, 40_000, "EUR"),
    ]
    assert r.json()[0]["logo_url"].startswith("https://cdntpfiles86236.tipsterpage.com/")
    peru = client.get("/billing/payment-methods", params={"country": "PE"}, headers=auth(token)).json()
    assert peru[1]["fields"] == ["first_name", "phone"]


def test_sin_pais_solo_los_medios_que_no_dependen_del_pais(client, db, tipster) -> None:
    """"Otro pais": de todo el catalogo, solo los medios sin restriccion."""
    token, _, _ = _cuenta(client, db)
    r = client.get("/billing/payment-methods", headers=auth(token))
    assert [m["key"] for m in r.json()] == ["cardtpv"]


def test_el_catalogo_sin_pasarela_caido_o_con_un_pais_mal_escrito(client, db, tipster) -> None:
    token, _, _ = _cuenta(client, db)
    assert client.get("/billing/payment-methods", params={"country": "col"}, headers=auth(token)).status_code == 422
    tipster.caido = True
    r = client.get("/billing/payment-methods", params={"country": "ES"}, headers=auth(token))
    assert (r.status_code, r.json()["detail"]["code"]) == (502, "provider_unavailable")


def test_el_catalogo_sin_pasarela(client, db) -> None:
    token, _, _ = _cuenta(client, db)
    r = client.get("/billing/payment-methods", headers=auth(token))
    assert (r.status_code, r.json()["detail"]["code"]) == (503, "payments_unavailable")


# ---------- El medio elegido se valida antes de escribir nada ----------


@pytest.mark.parametrize(
    ("cambios", "codigo"),
    [
        ({"metodo": None}, "payment_method_required"),
        ({"metodo": "paypal"}, "payment_method_unavailable"),
        # Un medio local sin pais, o con el de otro pais.
        ({"metodo": "ebanxpsecolombia"}, "payment_method_unavailable"),
        ({"metodo": "ebanxpsecolombia", "pais": "MX"}, "payment_method_unavailable"),
        # PSE pide el nombre.
        ({"metodo": "ebanxpsecolombia", "pais": "CO"}, "buyer_field_required"),
        ({"metodo": "ebanxpsecolombia", "pais": "CO", "comprador": {"first_name": "  "}}, "buyer_field_required"),
        # Bizum admite hasta 12 EUR en el catalogo simulado; el plan cuesta 32.
        ({"metodo": "bizum", "pais": "ES"}, "amount_out_of_range"),
    ],
)
def test_un_medio_que_no_sirve_no_abre_el_pago(client, db, tipster, cambios, codigo) -> None:
    token, user_id, _ = _cuenta(client, db)
    r = _suscribir(client, token, _mensual(db).id, **cambios)
    assert (r.status_code, r.json()["detail"]["code"]) == (400, codigo), r.text
    assert _pagos(db, user_id) == [] and _suscripciones(db, user_id) == []
    assert tipster.pedidos == []


def test_un_cupon_que_deja_el_total_bajo_el_minimo_del_medio(client, db, tipster) -> None:
    """Los medios de Tipster Page cobran desde 1 EUR."""
    token, user_id, _ = _cuenta(client, db)
    cupon = _cupon(db, value=99)  # 32 EUR - 99 % = 0,32 EUR
    r = _suscribir(client, token, _mensual(db).id, cupon.code)
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "amount_out_of_range")
    assert _pagos(db, user_id) == []


def test_un_medio_local_lleva_el_pais_y_solo_los_datos_que_pide(client, db, tipster) -> None:
    token, _, _ = _cuenta(client, db)
    r = _suscribir(
        client,
        token,
        _mensual(db).id,
        metodo="ebanxpsecolombia",
        pais="CO",
        comprador={"first_name": " Ana María ", "phone": "+57 300", "personal_id": "123"},
    )
    assert r.status_code == 202, r.text
    [pedido] = tipster.pedidos
    assert (pedido["payment_method"], pedido["country"], pedido["firstName"]) == (
        "ebanxpsecolombia",
        "CO",
        "Ana María",
    )
    # Lo que el medio no pide no sale.
    assert "phone" not in pedido and "personalId" not in pedido and "lastName" not in pedido


def test_si_la_pasarela_rechaza_la_orden_el_pago_queda_en_error(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db)
    tipster.respuesta_orden = (400, "Invalid signature")
    r = _suscribir(client, token, _mensual(db).id)
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "checkout_rejected")
    [pago] = _pagos(db, user_id)
    assert (pago.status, pago.failure_reason, pago.provider_transaction_id) == (
        "error",
        CHECKOUT_FAILED,
        None,
    )
    assert not _tiene_acceso(client, token)


@pytest.mark.parametrize("codigo", [401, 500, 502])
def test_si_la_pasarela_falla_al_crear_la_orden(client, db, tipster, codigo) -> None:
    """502 es EBANX sin redireccion: la orden queda pendiente del lado de
    ellos. El pago queda en error sin transaccion: si llegara su aviso, todavia
    lo resolveria."""
    token, user_id, _ = _cuenta(client, db)
    tipster.respuesta_orden = (codigo, "fallo")
    r = _suscribir(client, token, _mensual(db).id)
    assert (r.status_code, r.json()["detail"]["code"]) == (502, "provider_unavailable")
    [pago] = _pagos(db, user_id)
    assert (pago.status, pago.provider_transaction_id) == ("error", None)

    tipster.pagar(pago, "paid")
    assert _webhook(client, tipster.aviso(pago, "ok")).status_code == 200
    assert _tiene_acceso(client, token)


def test_si_la_pasarela_no_responde_al_crear_la_orden(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db)
    # El catalogo ya esta en la memoria del proveedor; la red cae despues.
    client.get("/billing/payment-methods", headers=auth(token))
    tipster.caido = True
    r = _suscribir(client, token, _mensual(db).id)
    assert (r.status_code, r.json()["detail"]["code"]) == (502, "provider_unavailable")
    assert [p.status for p in _pagos(db, user_id)] == ["error"]


# ---------- La pagina de pago de un solo uso ----------


def _enlace(client, db, token: str) -> str:
    r = _suscribir(client, token, _mensual(db).id)
    assert r.status_code == 202, r.text
    return httpx.URL(r.json()["checkout_url"]).path


def test_la_pagina_de_pago_se_abre_una_sola_vez_sin_sesion(client, db, tipster) -> None:
    token, _, _ = _cuenta(client, db)
    enlace = _enlace(client, db, token)

    r = client.get(enlace)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "sis-t.redsys.es" in r.text and r.headers["cache-control"] == "no-store"

    # Una recarga no la vuelve a mostrar, ni crea otra orden.
    otra = client.get(enlace)
    assert otra.status_code == 410 and "ya se usó" in otra.text
    assert "/planes" in otra.text
    assert len(tipster.pedidos) == 1


def test_la_csp_de_la_pagina_deja_correr_solo_sus_scripts(client, db, tipster) -> None:
    token, _, _ = _cuenta(client, db)
    csp = client.get(_enlace(client, db, token)).headers["content-security-policy"]
    directivas = dict(d.strip().split(" ", 1) for d in csp.split(";"))
    assert directivas["default-src"] == "'none'"
    assert directivas["script-src"].startswith("'sha256-") and "unsafe-inline" not in directivas["script-src"]
    # El TPV del formulario y el frontend, a donde puede redirigir la respuesta.
    frontend = get_settings().frontend_base_url.rstrip("/")
    assert set(directivas["form-action"].split()) == {"'self'", "https://sis-t.redsys.es:25443", frontend}
    assert directivas["frame-ancestors"] == "'none'"


def test_un_enlace_inventado_o_vencido_no_abre_nada(client, db, tipster, monkeypatch) -> None:
    assert client.get("/billing/checkout/" + "x" * 43).status_code == 410
    token, _, _ = _cuenta(client, db)
    enlace = _enlace(client, db, token)
    # Pasados los diez minutos.
    import time as reloj

    ahora = reloj.monotonic()
    monkeypatch.setattr(checkout_pages.time, "monotonic", lambda: ahora + checkout_pages.TTL_SECONDS + 1)
    assert client.get(enlace).status_code == 410


# ---------- Los datos del comprador no se guardan ----------


def test_los_datos_del_comprador_viajan_y_no_se_guardan(client, db, tipster, caplog) -> None:
    """Decidido el 2026-11-03: a Tipster Page, y a ningun otro lado."""
    caplog.set_level(logging.DEBUG)
    nombre, telefono = "NombreSecreto-7f3a", "+51-999-SECRETO"
    token, _, _ = _cuenta(client, db)
    r = _suscribir(
        client,
        token,
        _mensual(db).id,
        metodo="ebanxyapeperu",
        pais="PE",
        comprador={"first_name": nombre, "phone": telefono},
    )
    assert r.status_code == 202, r.text
    assert (tipster.pedidos[0]["firstName"], tipster.pedidos[0]["phone"]) == (nombre, telefono)
    pagina = client.get(httpx.URL(r.json()["checkout_url"]).path).text

    # Tambien cuando la pasarela rechaza la orden.
    tipster.respuesta_orden = (400, "Missing buyer field")
    _suscribir(
        client, token, _mensual(db).id, metodo="ebanxyapeperu", pais="PE",
        comprador={"first_name": nombre, "phone": telefono},
    )

    tablas = db.scalars(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    ).all()
    for tabla in tablas:
        for secreto in (nombre, telefono):
            filas = db.scalar(
                text(f'SELECT count(*) FROM "{tabla}" t WHERE row_to_json(t)::text LIKE :s'),
                {"s": f"%{secreto}%"},
            )
            assert filas == 0, (tabla, secreto)
    registros = "\n".join(r.getMessage() for r in caplog.records)
    assert nombre not in registros and telefono not in registros
    assert nombre not in pagina


# ---------- El job reconsulta los pendientes ----------


@pytest.fixture
def sin_pagos_de_otros_tests(db) -> None:
    for tabla in ("invoices", "payment_events", "payments", "coupon_redemptions", "subscriptions"):
        db.execute(text(f"DELETE FROM {tabla}"))
    db.commit()


def _correr(db, tipster: TipsterSandbox, cuando: datetime):
    reporte = run_renewals(db, tipster.provider, FakeEmailSender(), cuando)
    db.expire_all()
    return reporte


def test_el_job_resuelve_un_pago_cuyo_aviso_no_llego(client, db, tipster, sin_pagos_de_otros_tests) -> None:
    """Decidido el 2026-11-03: no se depende de los reintentos del aviso."""
    token, user_id, correo = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tipster.pagar(pago, "paid")  # pago, pero el aviso nunca llega

    reporte = _correr(db, tipster, datetime.now(UTC))
    assert (reporte.requeried, reporte.approved) == (1, 1)
    assert _pagos(db, user_id)[0].status == "approved"
    assert _tiene_acceso(client, token)
    assert "Recibo de tu pago en Sebasanálisis" in [m.subject for m in reporte.emails if m.to == correo]

    # La corrida siguiente no lo vuelve a tocar.
    assert _correr(db, tipster, datetime.now(UTC)).requeried == 0


def test_el_job_deja_quieto_un_pago_que_sigue_pendiente(client, db, tipster, sin_pagos_de_otros_tests) -> None:
    token, user_id, _ = _cuenta(client, db)
    _abrir_pago(client, db, token)
    reporte = _correr(db, tipster, datetime.now(UTC))
    assert (reporte.requeried, reporte.approved, reporte.failed) == (1, 0, 0)
    assert _pagos(db, user_id)[0].status == "pending"


def test_el_job_no_reconsulta_un_pendiente_de_hace_mas_de_una_semana(
    client, db, tipster, sin_pagos_de_otros_tests
) -> None:
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tipster.pagar(pago, "paid")
    reporte = _correr(db, tipster, datetime.now(UTC) + timedelta(days=8))
    assert reporte.requeried == 0
    assert _pagos(db, user_id)[0].status == "pending"


def test_si_la_pasarela_no_responde_el_job_lo_cuenta_y_sigue(client, db, tipster, sin_pagos_de_otros_tests) -> None:
    token, _, _ = _cuenta(client, db)
    _abrir_pago(client, db, token)
    tipster.caido = True
    reporte = _correr(db, tipster, datetime.now(UTC))
    assert (reporte.requeried, reporte.errors) == (0, 1)


# ---------- Reconsultar desde el admin ----------


def test_el_admin_reconsulta_un_pago_de_tipster_page(client, db, tipster, admin_token) -> None:
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tipster.pagar(pago, "paid")
    r = client.post(
        f"/admin/payments/{pago.id}/requery",
        json={"reason": "El cliente dice que pagó"},
        headers=auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert _pagos(db, user_id)[0].status == "approved"
    assert _tiene_acceso(client, token)



# ---------- Una orden abandonada deja de contar como cobro en proceso ----------


def _envejecer(db, pago: Payment, dias: int) -> None:
    db.execute(
        text("UPDATE payments SET created_at = :c WHERE id = :id"),
        {"c": datetime.now(UTC) - timedelta(days=dias), "id": pago.id},
    )
    db.commit()


def test_una_orden_abierta_impide_eliminar_la_cuenta_hasta_los_siete_dias(client, db, tipster) -> None:
    """Decidido el 2026-11-04: con Tipster Page la orden existe desde que se abre
    el pago. Mientras sea reciente, se espera; pasada una semana, se da por
    abandonada y no detiene nada."""
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    cuerpo = {"password": "clave-segura-123"}

    r = client.request("DELETE", "/auth/me", json=cuerpo, headers=auth(token))
    assert r.status_code == 409 and "pago en proceso" in r.json()["detail"]

    _envejecer(db, pago, 8)
    assert client.request("DELETE", "/auth/me", json=cuerpo, headers=auth(token)).status_code == 204


def test_una_orden_abandonada_no_detiene_al_administrador(client, db, tipster, admin_token) -> None:
    token, user_id, _ = _cuenta(client, db)
    _aprobar(client, tipster, _abrir_pago(client, db, token))
    segundo = _abrir_pago(client, db, token)  # el periodo siguiente, sin pagar
    [suscripcion] = [s for s in _suscripciones(db, user_id) if s.status == "active"]

    def extender():
        return client.patch(
            f"/admin/subscriptions/{suscripcion.id}",
            json={"action": "extend", "days": 3, "reason": "Compensacion de prueba"},
            headers=auth(admin_token),
        )

    r = extender()
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "charge_in_progress")
    _envejecer(db, segundo, 8)
    assert extender().status_code == 200
