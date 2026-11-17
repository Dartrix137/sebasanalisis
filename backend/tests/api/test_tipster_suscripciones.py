"""Renovacion automatica con las suscripciones de Tipster Page (paso 5.3b).

El `TipsterPageProvider` de verdad sobre el transporte simulado
(`tipster_sandbox.py`, `SuscripcionesSandbox`), que verifica la firma canonica
con su propio calculo. El job de renovaciones se llama directo con el `now`
que cada test necesita.
"""

import json
from datetime import timedelta

import pytest
from sqlalchemy import select, text

from app.billing.periods import add_interval
from app.core.email import FakeEmailSender
from app.core.renewals import run_renewals
from app.models import Payment, PaymentEvent, Plan
from tests.api.conftest import auth
from tests.api.test_billing import _mensual
from tests.api.test_subscriptions import (
    _asuntos,
    _cuenta,
    _pagos,
    _suscripciones,
    _tiene_acceso,
    _webhook,
)
from tests.api.tipster_sandbox import MERCHANT, TipsterSandbox

H = timedelta(hours=1)
DIA = timedelta(days=1)


@pytest.fixture(autouse=True)
def sin_suscripciones_de_otros_tests(db) -> None:
    """El job recorre todas las suscripciones de la base."""
    for tabla in ("invoices", "payment_events", "payments", "coupon_redemptions", "subscriptions"):
        db.execute(text(f"DELETE FROM {tabla}"))
    db.commit()


def _alta(client, token: str, plan_id, **cambios):
    body = {"plan_id": str(plan_id), "renewal_mode": "automatic", "country": "CO", **cambios}
    return client.post("/billing/subscriptions", json=body, headers=auth(token))


def _pago(db, user_id: str) -> Payment:
    [pago] = _pagos(db, user_id)
    return pago


def _consultar(client, token: str, pago: Payment) -> dict:
    r = client.get(f"/billing/payments/{pago.id}", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _suscriptor(client, db, tipster: TipsterSandbox, tarjeta: str = "ok"):
    """Una cuenta con el alta pagada en la pagina de Solidgate."""
    token, user_id, correo = _cuenta(client, db)
    assert _alta(client, token, _mensual(db).id).status_code == 202
    pago = _pago(db, user_id)
    tipster.suscripciones.pagar_alta(pago.reference, tarjeta)
    assert _consultar(client, token, pago)["status"] == "approved"
    [suscripcion] = _suscripciones(db, user_id)
    return token, user_id, correo, suscripcion


def _correr(db, tipster: TipsterSandbox, cuando):
    reporte = run_renewals(db, tipster.provider, FakeEmailSender(), cuando)
    db.expire_all()
    return reporte


# ---------- Disponibilidad ----------


def test_con_tipster_page_se_ofrece_la_renovacion_automatica(client, tipster) -> None:
    assert client.get("/billing/availability").json() == {
        "enabled": True,
        "automatic_renewal": True,
    }


def test_sin_suscripciones_en_la_pasarela_no_se_ofrece(client, db, tipster) -> None:
    tipster.suscripciones.activas = False
    assert client.get("/billing/availability").json()["automatic_renewal"] is False
    token, user_id, _ = _cuenta(client, db)
    r = _alta(client, token, _mensual(db).id)
    assert (r.status_code, r.json()["detail"]["code"]) == (503, "automatic_unavailable")
    assert _pagos(db, user_id) == []


# ---------- Alta ----------


def test_el_alta_crea_la_suscripcion_firmada_y_devuelve_la_pagina_de_solidgate(
    client, db, tipster
) -> None:
    token, user_id, correo = _cuenta(client, db)
    r = _alta(client, token, _mensual(db).id)
    assert r.status_code == 202, r.text
    pago = _pago(db, user_id)
    [(accion, cuerpo)] = tipster.suscripciones.pedidos
    suscripcion = tipster.suscripciones.de_pago(pago.reference)
    # La firma la verifico el simulado; el cuerpo lleva lo que pide el OpenAPI.
    assert accion == "CREATE"
    assert cuerpo["amount"] == 32 and isinstance(cuerpo["amount"], int)
    assert (cuerpo["periodicity"], cuerpo["external_id"], cuerpo["email"]) == (
        "mensual",
        pago.reference,
        correo,
    )
    assert (cuerpo["country"], cuerpo["language"], cuerpo["terms_accepted"]) == ("CO", "es", True)
    assert cuerpo["notification_url"].endswith("/webhooks/payments")
    assert cuerpo["url_ok"].endswith(f"/pago/{pago.id}")
    assert r.json()["checkout_url"] == suscripcion["checkout_url"]
    assert pago.provider_transaction_id == (
        f"sub:{suscripcion['subscription_id']}:initial:{pago.reference}"
    )
    assert (pago.status, pago.kind) == ("pending", "initial")

    # Mientras no pague, sigue pendiente aunque se consulte.
    assert _consultar(client, token, pago)["status"] == "pending"
    assert not _tiene_acceso(client, token)


def test_el_plan_de_dos_meses_va_como_bimestral(client, db, tipster) -> None:
    token, _, _ = _cuenta(client, db)
    bimestral = db.scalar(select(Plan).where(Plan.code == "bimestral"))
    assert _alta(client, token, bimestral.id).status_code == 202
    [(_, cuerpo)] = tipster.suscripciones.pedidos
    assert (cuerpo["periodicity"], cuerpo["amount"]) == ("bimestral", 46)


def test_al_pagar_el_alta_se_activa_y_guarda_la_suscripcion_de_la_pasarela(
    client, db, tipster, outbox
) -> None:
    token, user_id, correo = _cuenta(client, db)
    outbox.clear()
    assert _alta(client, token, _mensual(db).id).status_code == 202
    pago = _pago(db, user_id)
    remota = tipster.suscripciones.pagar_alta(pago.reference)

    assert _consultar(client, token, pago)["status"] == "approved"
    [suscripcion] = _suscripciones(db, user_id)
    assert (suscripcion.status, suscripcion.renewal_mode) == ("active", "automatic")
    assert (
        suscripcion.provider_subscription_id,
        suscripcion.payment_source_id,
        suscripcion.payment_source_type,
    ) == (remota["subscription_id"], remota["payment_method_id"], "CARD")
    assert _tiene_acceso(client, token)
    assert _asuntos(outbox, correo) == [
        "Tu suscripción a Sebasanálisis está activa",
        "Recibo de tu pago en Sebasanálisis",
    ]
    # Su factura nace con el pago, como la de cualquier pago aprobado.
    assert db.execute(
        text("SELECT status FROM invoices WHERE payment_id = :p"), {"p": pago.id}
    ).scalar() == "pending"


def test_primer_pago_rechazado_no_da_acceso(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db)
    assert _alta(client, token, _mensual(db).id).status_code == 202
    pago = _pago(db, user_id)
    tipster.suscripciones.pagar_alta(pago.reference, "rechazada")
    assert _consultar(client, token, pago)["status"] == "declined"
    [suscripcion] = _suscripciones(db, user_id)
    assert (suscripcion.status, suscripcion.provider_subscription_id) == ("pending", None)
    assert not _tiene_acceso(client, token)


def test_un_alta_de_otro_pago_no_se_le_cree(client, db, tipster) -> None:
    """Si la suscripcion de la pasarela no trae nuestra referencia como
    `external_id`, la reconsulta no le cree nada."""
    token, user_id, _ = _cuenta(client, db)
    assert _alta(client, token, _mensual(db).id).status_code == 202
    pago = _pago(db, user_id)
    remota = tipster.suscripciones.pagar_alta(pago.reference)
    tipster.suscripciones.suscripciones[remota["subscription_id"]]["external_id"] = "OTRO-PAGO"
    assert _consultar(client, token, pago)["status"] == "pending"
    assert not _tiene_acceso(client, token)


def test_si_la_pasarela_rechaza_el_alta_el_pago_queda_en_error(client, db, tipster, monkeypatch) -> None:
    token, user_id, _ = _cuenta(client, db)
    monkeypatch.setattr(tipster.provider, "_secret_key", "otra-clave")
    r = _alta(client, token, _mensual(db).id)
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "checkout_rejected")
    pago = _pago(db, user_id)
    assert (pago.status, pago.provider_transaction_id) == ("error", None)


def test_si_la_pasarela_no_responde_al_crear_el_alta(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db)
    tipster.caido = True
    r = _alta(client, token, _mensual(db).id)
    # Sin red ni siquiera se puede consultar el medio: no se escribe nada.
    assert (r.status_code, r.json()["detail"]["code"]) == (502, "provider_unavailable")
    assert _pagos(db, user_id) == []


# ---------- Avisos de la suscripcion ----------


def test_el_aviso_del_alta_activa_la_suscripcion_y_un_duplicado_no_repite(
    client, db, tipster, outbox
) -> None:
    token, user_id, correo = _cuenta(client, db)
    assert _alta(client, token, _mensual(db).id).status_code == 202
    pago = _pago(db, user_id)
    remota = tipster.suscripciones.pagar_alta(pago.reference)
    outbox.clear()

    aviso = tipster.suscripciones.aviso(
        remota, "subscription.payment_succeeded", {"period_id": "initial", "paid_status": "paid"},
        event_id="evento-1",
    )
    r = _webhook(client, aviso)
    assert (r.status_code, r.json()) == (200, {"status": "processed"})
    assert _pago(db, user_id).status == "approved"
    assert _tiene_acceso(client, token)
    assert len(_asuntos(outbox, correo)) == 2

    # Tipster Page reintenta con el mismo `event_id`: no se procesa otra vez.
    r = _webhook(client, aviso)
    assert (r.status_code, r.json()) == (200, {"status": "duplicate"})
    assert len(_asuntos(outbox, correo)) == 2
    evento = db.scalar(
        select(PaymentEvent).where(PaymentEvent.provider_event_id == "tipsterpage:sub:evento-1")
    )
    assert evento is not None and evento.signature_verified and evento.payment_id == pago.id


def test_un_aviso_mal_firmado_no_mueve_nada(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db)
    assert _alta(client, token, _mensual(db).id).status_code == 202
    pago = _pago(db, user_id)
    remota = tipster.suscripciones.pagar_alta(pago.reference)
    aviso = tipster.suscripciones.aviso(remota, "subscription.created", firma="0" * 64)
    assert _webhook(client, aviso).status_code == 401
    assert _pago(db, user_id).status == "pending"
    assert not _tiene_acceso(client, token)


def test_el_aviso_no_es_la_fuente_de_verdad(client, db, tipster) -> None:
    """Un aviso de pago bien firmado, pero la reconsulta dice que no se pago."""
    token, user_id, _ = _cuenta(client, db)
    assert _alta(client, token, _mensual(db).id).status_code == 202
    pago = _pago(db, user_id)
    remota = tipster.suscripciones.de_pago(pago.reference)
    aviso = tipster.suscripciones.aviso(remota, "subscription.payment_succeeded", {"paid_status": "paid"})
    assert _webhook(client, aviso).status_code == 200
    assert _pago(db, user_id).status == "pending"
    assert not _tiene_acceso(client, token)


def test_el_aviso_de_una_devolucion_se_acepta_sin_mover_nada(client, db, tipster) -> None:
    token, user_id, _, _ = _suscriptor(client, db, tipster)
    remota = tipster.suscripciones.de_pago(_pago(db, user_id).reference)
    aviso = tipster.suscripciones.aviso(
        remota, "subscription.payment_refunded", {"paid_status": "refund", "amount": 32}
    )
    assert _webhook(client, aviso).json() == {"status": "acknowledged"}
    assert _pago(db, user_id).status == "approved"
    assert _tiene_acceso(client, token)


def test_sin_pasarela_caida_el_aviso_se_reintenta(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db)
    assert _alta(client, token, _mensual(db).id).status_code == 202
    pago = _pago(db, user_id)
    remota = tipster.suscripciones.pagar_alta(pago.reference)
    aviso = tipster.suscripciones.aviso(remota, "subscription.created")
    tipster.caido = True
    assert _webhook(client, aviso).status_code == 502
    tipster.caido = False
    assert _webhook(client, aviso).json() == {"status": "processed"}
    assert _pago(db, user_id).status == "approved"


# ---------- Renovacion ----------


def test_la_renovacion_cobra_con_charge_firmado_y_extiende_el_periodo(client, db, tipster) -> None:
    token, user_id, _, suscripcion = _suscriptor(client, db, tipster)
    vence = suscripcion.current_period_end
    assert _correr(db, tipster, vence - 9 * DIA).notices == 1
    reporte = _correr(db, tipster, vence - 48 * H)
    assert (reporte.charges, reporte.approved) == (1, 1)

    accion, cuerpo = tipster.suscripciones.pedidos[-1]
    assert accion == "CHARGE"
    assert cuerpo["period_id"] == f"p{int(vence.timestamp())}"
    assert cuerpo["payment_method_id"] == suscripcion.payment_source_id
    assert cuerpo["amount"] == 32
    assert cuerpo["period_end"] == add_interval(vence, "month", 1).strftime("%Y-%m-%dT%H:%M:%SZ")
    [suscripcion] = _suscripciones(db, user_id)
    assert suscripcion.current_period_end == add_interval(vence, "month", 1)
    renovacion = _pagos(db, user_id)[-1]
    assert (renovacion.kind, renovacion.status) == ("renewal", "approved")
    assert renovacion.provider_transaction_id.startswith(f"sub:{suscripcion.provider_subscription_id}:")


def test_los_reintentos_van_al_mismo_periodo_con_otra_clave(client, db, tipster) -> None:
    token, user_id, _, suscripcion = _suscriptor(client, db, tipster, tarjeta="falla_renovacion")
    vence = suscripcion.current_period_end
    _correr(db, tipster, vence - 9 * DIA)
    assert _correr(db, tipster, vence - 48 * H).failed == 1
    assert _suscripciones(db, user_id)[0].status == "past_due"
    assert _correr(db, tipster, vence - 24 * H).failed == 1

    cobros = [c for a, c in tipster.suscripciones.pedidos if a == "CHARGE"]
    assert len(cobros) == 2
    assert cobros[0]["period_id"] == cobros[1]["period_id"]
    assert cobros[0]["period_end"] == cobros[1]["period_end"]
    assert cobros[0]["amount"] == cobros[1]["amount"]
    assert cobros[0]["idempotency_key"] != cobros[1]["idempotency_key"]


def test_un_cobro_pendiente_se_reconsulta_en_la_corrida_siguiente(client, db, tipster) -> None:
    token, user_id, _, suscripcion = _suscriptor(client, db, tipster)
    vence = suscripcion.current_period_end
    _correr(db, tipster, vence - 9 * DIA)
    tipster.suscripciones.resultado_del_cobro = "PENDING"
    assert _correr(db, tipster, vence - 48 * H).charges == 1
    renovacion = _pagos(db, user_id)[-1]
    assert renovacion.status == "pending"

    pid = renovacion.provider_transaction_id.split(":")[2]
    tipster.suscripciones.cobros[pid]["status"] = "PAID"
    reporte = _correr(db, tipster, vence - 47 * H)
    assert (reporte.charges, reporte.approved) == (0, 1)
    assert _suscripciones(db, user_id)[0].current_period_end == add_interval(vence, "month", 1)


def test_el_aviso_de_una_renovacion_la_resuelve(client, db, tipster) -> None:
    token, user_id, _, suscripcion = _suscriptor(client, db, tipster)
    vence = suscripcion.current_period_end
    _correr(db, tipster, vence - 9 * DIA)
    tipster.suscripciones.resultado_del_cobro = "PENDING"
    _correr(db, tipster, vence - 48 * H)
    renovacion = _pagos(db, user_id)[-1]
    pid = renovacion.provider_transaction_id.split(":")[2]
    tipster.suscripciones.cobros[pid]["status"] = "PAID"

    remota = tipster.suscripciones.suscripciones[suscripcion.provider_subscription_id]
    aviso = tipster.suscripciones.aviso(
        remota, "subscription.renewed", {"payment_id": pid, "cycle": 2, "paid_status": "paid"}
    )
    assert _webhook(client, aviso).json() == {"status": "processed"}
    assert _pagos(db, user_id)[-1].status == "approved"


def test_un_cobro_que_la_pasarela_no_acepta_cuenta_como_intento(client, db, tipster) -> None:
    token, user_id, _, suscripcion = _suscriptor(client, db, tipster)
    vence = suscripcion.current_period_end
    _correr(db, tipster, vence - 9 * DIA)
    tipster.suscripciones.respuesta_cobro = (409, "Limite de reintentos")
    reporte = _correr(db, tipster, vence - 48 * H)
    assert (reporte.charges, reporte.failed) == (1, 1)
    renovacion = _pagos(db, user_id)[-1]
    assert (renovacion.status, renovacion.provider_transaction_id) == ("error", None)
    assert _suscripciones(db, user_id)[0].status == "past_due"
    # El acceso sigue: el periodo pagado no ha terminado.
    assert _tiene_acceso(client, token)


def test_en_la_base_no_queda_el_correo_en_el_cuerpo_del_aviso(client, db, tipster) -> None:
    """El aviso de una suscripcion no trae datos del comprador: se guarda tal cual."""
    token, user_id, _ = _cuenta(client, db)
    assert _alta(client, token, _mensual(db).id).status_code == 202
    pago = _pago(db, user_id)
    remota = tipster.suscripciones.pagar_alta(pago.reference)
    _webhook(client, tipster.suscripciones.aviso(remota, "subscription.created"))
    guardado = db.scalar(select(PaymentEvent.raw_payload).where(PaymentEvent.payment_id == pago.id))
    assert "@" not in json.dumps(guardado) and MERCHANT not in json.dumps(guardado)


# ---------- Entrega 3: 3DS, tarjeta sin reintento, cambio de tarjeta, modos ----------


def _correos(reporte) -> list:
    return [*reporte.sent, *reporte.emails]


def _vence_y_avisa(db, tipster, suscripcion):
    vence = suscripcion.current_period_end
    assert _correr(db, tipster, vence - 9 * DIA).notices == 1
    return vence


def _cobros(tipster) -> list[dict]:
    return [c for a, c in tipster.suscripciones.pedidos if a == "CHARGE"]


def test_un_cobro_con_3ds_queda_pendiente_y_se_le_manda_el_enlace(client, db, tipster) -> None:
    token, user_id, correo, suscripcion = _suscriptor(client, db, tipster)
    vence = _vence_y_avisa(db, tipster, suscripcion)
    tipster.suscripciones.resultado_del_cobro = "3DS"
    reporte = _correr(db, tipster, vence - 48 * H)
    assert reporte.charges == 1
    renovacion = _pagos(db, user_id)[-1]
    assert renovacion.status == "pending"
    [aviso] = [m for m in _correos(reporte) if m.to == correo]
    assert aviso.subject == "Confirma el cobro de tu suscripción a Sebasanálisis"
    pid = renovacion.provider_transaction_id.split(":")[2]
    assert f"https://3ds.solidgate.test/{pid}" in aviso.text

    # El enlace sale una vez: la corrida siguiente solo reconsulta.
    assert [m for m in _correos(_correr(db, tipster, vence - 47 * H)) if m.to == correo] == []
    # El cliente no confirmo y la pasarela lo rechazo: cuenta como intento.
    tipster.suscripciones.cobros[pid].update(status="FAILED", retry_allowed=True)
    reporte = _correr(db, tipster, vence - 46 * H)
    assert reporte.failed == 1
    assert _suscripciones(db, user_id)[0].status == "past_due"


def test_un_rechazo_sin_reintento_bloquea_la_tarjeta_y_pide_cambiarla(client, db, tipster) -> None:
    token, user_id, correo, suscripcion = _suscriptor(client, db, tipster)
    vence = _vence_y_avisa(db, tipster, suscripcion)
    tipster.suscripciones.resultado_del_cobro = "SIN_REINTENTO"
    reporte = _correr(db, tipster, vence - 48 * H)
    assert reporte.failed == 1
    [aviso] = [m for m in _correos(reporte) if m.to == correo]
    assert "no permite volver a intentar el cobro con esa tarjeta" in aviso.text
    assert "Vamos a intentarlo de nuevo" not in aviso.text
    [suscripcion] = _suscripciones(db, user_id)
    assert (suscripcion.status, suscripcion.payment_source_blocked) == ("past_due", True)
    assert client.get("/billing/subscription", headers=auth(token)).json()["card_update_required"]

    # Los otros dos intentos no salen: la tarjeta sigue bloqueada, y al
    # terminar el periodo sin otra tarjeta, vence, sin gracia.
    assert _correr(db, tipster, vence - 24 * H).charges == 0
    reporte = _correr(db, tipster, vence)
    assert (reporte.charges, reporte.expired) == (0, 1)
    assert len(_cobros(tipster)) == 1
    assert not _tiene_acceso(client, token)


def test_cambiar_la_tarjeta_bloqueada_la_recupera_y_cobra_el_periodo(
    client, db, tipster, outbox
) -> None:
    token, user_id, correo, suscripcion = _suscriptor(client, db, tipster)
    vence = _vence_y_avisa(db, tipster, suscripcion)
    tipster.suscripciones.resultado_del_cobro = "SIN_REINTENTO"
    _correr(db, tipster, vence - 48 * H)
    sid = suscripcion.provider_subscription_id
    vieja = suscripcion.payment_source_id

    # Con un cobro rechazado, el enlace es el de recuperacion.
    r = client.post("/billing/payment-method/checkout", headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["checkout_url"] == f"https://checkout.solidgate.test/tarjeta/{sid}"
    assert tipster.suscripciones.pedidos[-1][0] == "RECOVERY"

    # El cliente guarda otra tarjeta y vuelve: la cuenta sincroniza.
    tipster.suscripciones.resultado_del_cobro = "PAID"
    nueva = tipster.suscripciones.guardar_tarjeta(sid)["payment_method_id"]
    outbox.clear()
    r = client.post("/billing/payment-method/sync", headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["card_update_required"] is False
    [suscripcion] = _suscripciones(db, user_id)
    assert (suscripcion.payment_source_id, suscripcion.payment_source_blocked) == (nueva, False)
    # El cobro del periodo se reintento ya, con la tarjeta nueva y el mismo periodo.
    ultimo, primero = _cobros(tipster)[-1], _cobros(tipster)[0]
    assert (ultimo["payment_method_id"], ultimo["period_id"]) == (nueva, primero["period_id"])
    assert vieja != nueva
    assert suscripcion.status == "active"
    assert suscripcion.current_period_end == add_interval(vence, "month", 1)
    assert "Cambió el medio de pago de tu suscripción a Sebasanálisis" in _asuntos(outbox, correo)


def test_cambiar_la_tarjeta_sin_cobro_pendiente_no_cobra_y_lo_trae_el_aviso(
    client, db, tipster
) -> None:
    token, user_id, _, suscripcion = _suscriptor(client, db, tipster)
    sid = suscripcion.provider_subscription_id
    r = client.post("/billing/payment-method/checkout", headers=auth(token))
    assert r.status_code == 200, r.text
    assert tipster.suscripciones.pedidos[-1][0] == "PAYMENT_METHOD"
    remota = tipster.suscripciones.guardar_tarjeta(sid)

    aviso = tipster.suscripciones.aviso(
        remota,
        "subscription.payment_method_updated",
        {"payment_method_id": remota["payment_method_id"]},
    )
    assert _webhook(client, aviso).json() == {"status": "processed"}
    [suscripcion] = _suscripciones(db, user_id)
    assert suscripcion.payment_source_id == remota["payment_method_id"]
    assert _cobros(tipster) == []


def test_el_job_recoge_la_tarjeta_nueva_si_el_aviso_no_llego(client, db, tipster) -> None:
    token, user_id, _, suscripcion = _suscriptor(client, db, tipster)
    vence = _vence_y_avisa(db, tipster, suscripcion)
    tipster.suscripciones.resultado_del_cobro = "SIN_REINTENTO"
    _correr(db, tipster, vence - 48 * H)
    sid = suscripcion.provider_subscription_id
    assert client.post("/billing/payment-method/checkout", headers=auth(token)).status_code == 200
    tipster.suscripciones.resultado_del_cobro = "PAID"
    nueva = tipster.suscripciones.guardar_tarjeta(sid)["payment_method_id"]

    # Sin aviso ni sincronizacion de la cuenta: la corrida siguiente la lee
    # de la pasarela y reintenta el cobro con ella.
    _correr(db, tipster, vence - 30 * H)
    assert _cobros(tipster)[-1]["payment_method_id"] == nueva
    assert _suscripciones(db, user_id)[0].current_period_end == add_interval(vence, "month", 1)


def test_de_pago_manual_a_automatica_verifica_la_tarjeta_sin_cobrar(client, db, tipster) -> None:
    from tests.api.test_subscriptions import _abrir_pago, _aprobar

    token, user_id, _ = _cuenta(client, db)
    _aprobar(client, tipster, _abrir_pago(client, db, token))
    [suscripcion] = _suscripciones(db, user_id)
    assert suscripcion.renewal_mode == "manual"

    r = client.post("/billing/payment-method/checkout", headers=auth(token))
    assert r.status_code == 200, r.text
    accion, cuerpo = tipster.suscripciones.pedidos[-1]
    assert (accion, cuerpo["setup_only"], cuerpo["amount"]) == ("CREATE", True, 32)
    assert cuerpo["external_id"].startswith("SA-S-") and cuerpo["country"] == "CO"
    # Mientras no verifique la tarjeta, sigue de pago manual.
    assert _suscripciones(db, user_id)[0].renewal_mode == "manual"

    tipster.suscripciones.verificar(cuerpo["external_id"])
    r = client.post("/billing/payment-method/sync", headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["renewal_mode"] == "automatic"
    [suscripcion] = _suscripciones(db, user_id)
    assert suscripcion.next_charge_at == suscripcion.current_period_end - 48 * H
    # No se cobro nada: ni el alta (solo verifico) ni una renovacion.
    assert _cobros(tipster) == [] and len(_pagos(db, user_id)) == 1


def test_pasar_a_pago_manual_borra_la_tarjeta_en_la_pasarela(client, db, tipster) -> None:
    token, user_id, _, suscripcion = _suscriptor(client, db, tipster)
    sid, metodo = suscripcion.provider_subscription_id, suscripcion.payment_source_id
    r = client.delete("/billing/payment-method", headers=auth(token))
    assert r.status_code == 200, r.text
    accion, cuerpo = tipster.suscripciones.pedidos[-1]
    assert (accion, cuerpo["scope"], cuerpo["payment_method_id"]) == (
        "DELETE_PAYMENT_METHOD",
        "SUBSCRIPTION",
        metodo,
    )
    assert tipster.suscripciones.suscripciones[sid]["status"] == "CANCELLED"
    [suscripcion] = _suscripciones(db, user_id)
    assert (suscripcion.renewal_mode, suscripcion.provider_subscription_id) == ("manual", None)


def test_eliminar_la_cuenta_borra_la_tarjeta_en_la_pasarela(client, db, tipster) -> None:
    from tests.api.test_subscription_changes import _eliminar

    token, user_id, _, suscripcion = _suscriptor(client, db, tipster)
    sid = suscripcion.provider_subscription_id
    assert _eliminar(client, token).status_code == 204
    assert tipster.suscripciones.pedidos[-1][0] == "DELETE_PAYMENT_METHOD"
    assert tipster.suscripciones.suscripciones[sid]["status"] == "CANCELLED"


def test_si_la_pasarela_no_borra_la_tarjeta_igual_se_pasa_a_manual(client, db, tipster, caplog) -> None:
    token, user_id, _, suscripcion = _suscriptor(client, db, tipster)
    tipster.caido = True
    r = client.delete("/billing/payment-method", headers=auth(token))
    tipster.caido = False
    assert r.status_code == 200, r.text
    assert _suscripciones(db, user_id)[0].renewal_mode == "manual"
    assert "borrarla a mano" in caplog.text
