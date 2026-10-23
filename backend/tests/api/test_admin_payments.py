"""Admin: suscripciones y pagos (§4.3 de la Fase 4, paso 6, entrega 1).

Extender, cancelar al final del periodo y cancelar de inmediato; listas y
detalle de suscripciones y pagos; reconsultar un pago; registrar un reembolso;
y el pago aprobado que el proveedor anula despues.

La pasarela es el doble de `pasarela_double.py`, y el job de renovaciones se llama directo con el `now` que cada caso necesita.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from app.billing.periods import add_interval
from app.models import AdminAuditLog, Payment, PaymentEvent, PaymentRefund, Plan, Subscription
from tests.api.conftest import auth
from tests.api.test_billing import _mensual
from tests.api.test_renewals import _avisada, _correos, _correr, _suscriptor_automatico
from tests.api.test_subscriptions import (
    PRECIO,
    _abrir_pago,
    _aprobar,
    _asuntos,
    _cuenta,
    _pagos,
    _suscripciones,
    _tiene_acceso,
    _webhook,
)

H = timedelta(hours=1)
DIA = timedelta(days=1)
MOTIVO = "Compensación por la caída del 13 de octubre"


@pytest.fixture(autouse=True)
def sin_suscripciones_de_otros_tests(db) -> None:
    """El job recorre todas las suscripciones de la base: cada test empieza sin
    las de los demas, ni sus filas de bitacora."""
    for tabla in (
        "payment_refunds",
        "payment_events",
        "payments",
        "coupon_redemptions",
        "subscriptions",
    ):
        db.execute(text(f"DELETE FROM {tabla}"))
    # La bitacora no se borra en la aplicacion; en la base de test, las filas de
    # suscripciones y pagos de otros tests estorban al contar las de este.
    db.execute(text("DELETE FROM admin_audit_log WHERE target_type IN ('subscription', 'payment')"))
    db.commit()


# ---------- Ayudas ----------


def _suscriptor_manual(client, db, pasarela) -> tuple[str, str, str, Subscription]:
    """Una cuenta con el primer pago manual aprobado."""
    token, user_id, correo = _cuenta(client, db)
    _aprobar(client, pasarela, _abrir_pago(client, db, token))
    [suscripcion] = _suscripciones(db, user_id)
    assert suscripcion.status == "active"
    return token, user_id, correo, suscripcion


def _accion(client, admin_token: str, subscription_id, action: str, **body):
    payload = {"action": action, "reason": MOTIVO, **body}
    return client.patch(
        f"/admin/subscriptions/{subscription_id}", json=payload, headers=auth(admin_token)
    )


def _filas(db, action: str) -> list[AdminAuditLog]:
    db.expire_all()
    return list(
        db.scalars(
            select(AdminAuditLog)
            .where(AdminAuditLog.action == action)
            .order_by(AdminAuditLog.created_at)
        )
    )


def _suscripcion(db, subscription_id) -> Subscription:
    db.expire_all()
    found = db.get(Subscription, subscription_id)
    assert found is not None
    return found


def _acceso(client, token: str) -> dict:
    return client.get("/auth/me", headers=auth(token)).json()["access"]


# ---------- Solo administradores ----------


_RUTAS = [
    ("GET", "/admin/subscriptions", None),
    ("GET", "/admin/subscriptions/{id}", None),
    ("PATCH", "/admin/subscriptions/{id}", {"action": "extend", "days": 3, "reason": MOTIVO}),
    ("GET", "/admin/payments", None),
    ("GET", "/admin/payments/{id}", None),
    ("POST", "/admin/payments/{id}/requery", {"reason": MOTIVO}),
    (
        "POST",
        "/admin/payments/{id}/refunds",
        {"amount_cents": 100, "refunded_at": "2026-10-01T00:00:00Z", "reason": MOTIVO},
    ),
]


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo"), _RUTAS)
def test_una_cuenta_que_no_es_administradora_recibe_403(
    client, db, pasarela, user_token: str, metodo: str, ruta: str, cuerpo
) -> None:
    _, _, _, suscripcion = _suscriptor_manual(client, db, pasarela)
    [pago] = _pagos(db, str(suscripcion.user_id))
    objetivo = suscripcion.id if "subscriptions" in ruta else pago.id
    url = ruta.replace("{id}", str(objetivo))

    r = client.request(metodo, url, json=cuerpo, headers=auth(user_token))
    assert r.status_code == 403, r.text
    assert client.request(metodo, url, json=cuerpo).status_code == 401
    # Nada cambio y nada quedo en la bitacora.
    assert _suscripcion(db, suscripcion.id).current_period_end == suscripcion.current_period_end
    assert db.scalar(select(func.count()).select_from(AdminAuditLog).where(
        AdminAuditLog.target_type.in_(("subscription", "payment"))
    )) == 0


def test_un_administrador_suspendido_tampoco_entra(client, db, pasarela, admin_token: str) -> None:
    db.execute(text("UPDATE users SET is_active = false WHERE role = 'admin'"))
    db.commit()
    try:
        assert client.get("/admin/subscriptions", headers=auth(admin_token)).status_code == 403
    finally:
        db.execute(text("UPDATE users SET is_active = true WHERE role = 'admin'"))
        db.commit()


# ---------- Lista y detalle de suscripciones ----------


def test_la_lista_filtra_por_estado_y_plan_en_el_servidor(client, db, pasarela, admin_token: str) -> None:
    _, _, correo_manual, manual = _suscriptor_manual(client, db, pasarela)
    _, _, _, automatica = _suscriptor_automatico(client, db, pasarela)
    bimestral = db.scalar(select(Plan).where(Plan.code == "bimestral"))
    token_b, _, correo_b = _cuenta(client, db)
    _aprobar(client, pasarela, _abrir_pago(client, db, token_b, plan=bimestral))
    # Un pago abierto y no completado deja una suscripcion `pending`.
    token_p, _, _ = _cuenta(client, db)
    _abrir_pago(client, db, token_p)
    # Una en mora y una vencida, puestas a mano.
    db.execute(
        text("UPDATE subscriptions SET status = 'past_due' WHERE id = :id"), {"id": automatica.id}
    )
    db.commit()

    def lista(**params) -> dict:
        r = client.get("/admin/subscriptions", params=params, headers=auth(admin_token))
        assert r.status_code == 200, r.text
        return r.json()

    todas = lista()
    assert todas["total"] == 3  # sin la `pending`
    assert {s["status"] for s in todas["items"]} == {"active", "past_due"}
    assert lista(status="pending")["total"] == 1
    assert [s["id"] for s in lista(status="past_due")["items"]] == [str(automatica.id)]
    assert lista(status="expired")["total"] == 0
    assert [s["user_email"] for s in lista(plan_id=str(bimestral.id))["items"]] == [correo_b]
    assert lista(renewal_mode="automatic")["total"] == 1
    assert [s["id"] for s in lista(query=correo_manual.upper())["items"]] == [str(manual.id)]
    # Los comodines se buscan literales.
    assert lista(query="%")["total"] == 0

    pagina = lista(limit=2, offset=0)
    assert (pagina["total"], len(pagina["items"]), pagina["limit"]) == (3, 2, 2)
    assert len(lista(limit=2, offset=2)["items"]) == 1
    assert client.get(
        "/admin/subscriptions", params={"limit": 101}, headers=auth(admin_token)
    ).status_code == 422


def test_el_detalle_trae_la_suscripcion_sus_pagos_y_su_bitacora(
    client, db, pasarela, admin_token: str
) -> None:
    _, user_id, correo, suscripcion = _suscriptor_manual(client, db, pasarela)
    assert _accion(client, admin_token, suscripcion.id, "extend", days=5).status_code == 200

    r = client.get(f"/admin/subscriptions/{suscripcion.id}", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert (data["subscription"]["user_email"], data["subscription"]["in_force"]) == (correo, True)
    assert [p["status"] for p in data["payments"]] == ["approved"]
    assert data["payments"][0]["user_email"] == correo
    assert [(a["action"], a["reason"]) for a in data["audit"]] == [("subscription.extend", MOTIVO)]

    r = client.get(f"/admin/subscriptions/{uuid.uuid4()}", headers=auth(admin_token))
    assert r.status_code == 404


# ---------- Extender ----------


def test_extender_corre_el_vencimiento_deja_fila_con_motivo_y_avisa(
    client, db, pasarela, admin_token: str, outbox
) -> None:
    token, user_id, correo, suscripcion = _suscriptor_manual(client, db, pasarela)
    vence = suscripcion.current_period_end
    outbox.clear()

    r = _accion(client, admin_token, suscripcion.id, "extend", days=10)
    assert r.status_code == 200, r.text
    nueva = vence + 10 * DIA
    assert _suscripcion(db, suscripcion.id).current_period_end == nueva
    # El acceso lo decide has_access, con el vencimiento nuevo.
    acceso = _acceso(client, token)
    assert (acceso["granted"], acceso["reason"]) == (True, "subscription")
    assert datetime.fromisoformat(acceso["until"]) == nueva

    [fila] = _filas(db, "subscription.extend")
    assert (fila.target_type, fila.target_id, fila.reason) == (
        "subscription",
        str(suscripcion.id),
        MOTIVO,
    )
    assert fila.before["current_period_end"] == vence.isoformat()
    assert fila.after["current_period_end"] == nueva.isoformat() and fila.after["days"] == 10
    # Ningun pago nuevo: extender no cobra.
    assert len(_pagos(db, user_id)) == 1

    assert _asuntos(outbox, correo) == ["Extendimos tu suscripción a Sebasanálisis"]
    [correo_enviado] = outbox
    assert "sin costo" in correo_enviado.text
    # El motivo es interno: no va al cliente.
    assert MOTIVO not in correo_enviado.text and MOTIVO not in correo_enviado.html
    # Pago manual: no habla de un cobro automatico.
    assert "próximo cobro" not in correo_enviado.text


def test_extender_una_renovacion_automatica_corre_el_cobro_y_el_aviso(
    client, db, pasarela, admin_token: str, outbox
) -> None:
    """Decidido el 2026-10-14: se corre todo. Lo que el job ya aviso para la
    fecha vieja no cuenta para la nueva."""
    _, user_id, correo, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = _avisada(db, pasarela, suscripcion)
    outbox.clear()

    r = _accion(client, admin_token, suscripcion.id, "extend", days=10)
    assert r.status_code == 200, r.text
    nueva = vence + 10 * DIA
    suscripcion = _suscripcion(db, suscripcion.id)
    assert suscripcion.next_charge_at == nueva - 48 * H
    assert r.json()["subscription"]["next_charge_at"] is not None
    [correo_enviado] = outbox
    assert "próximo cobro" in correo_enviado.text and "100.000 COP" in correo_enviado.text

    # A la hora del cobro viejo no se cobra ni se avisa.
    for cuando in (vence - 48 * H, vence - 24 * H, vence):
        reporte = _correr(db, pasarela, cuando)
        assert (reporte.charges, reporte.notices, reporte.expired) == (0, 0, 0)
    assert len(pasarela.cobros) == 1  # solo el del alta

    # El aviso sale otra vez, para la fecha nueva, y despues el cobro.
    reporte = _correr(db, pasarela, nueva - 48 * H - 7 * DIA)
    assert reporte.notices == 1
    reporte = _correr(db, pasarela, nueva - 48 * H)
    assert (reporte.charges, reporte.approved) == (1, 1)
    assert _suscripcion(db, suscripcion.id).current_period_end == add_interval(nueva, "month", 1)


def test_extender_una_suscripcion_en_mora_la_deja_activa(client, db, pasarela, admin_token: str) -> None:
    token, user_id, _, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = _avisada(db, pasarela, suscripcion)
    pasarela.estado_del_cobro = "DECLINED"
    assert _correr(db, pasarela, vence - 48 * H).failed == 1
    assert _suscripcion(db, suscripcion.id).status == "past_due"

    assert _accion(client, admin_token, suscripcion.id, "extend", days=3).status_code == 200
    suscripcion = _suscripcion(db, suscripcion.id)
    assert (suscripcion.status, suscripcion.retry_count) == ("active", 0)
    assert suscripcion.next_charge_at == vence + 3 * DIA - 48 * H
    assert _tiene_acceso(client, token)


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"action": "extend", "days": 5},
        {"action": "extend", "days": 5, "reason": ""},
        {"action": "extend", "days": 5, "reason": "ok"},
        {"action": "extend", "days": 5, "reason": "x" * 501},
        {"action": "extend", "reason": MOTIVO},
        {"action": "extend", "days": 0, "reason": MOTIVO},
        {"action": "extend", "days": 91, "reason": MOTIVO},
        {"action": "cancel_now", "days": 5, "reason": MOTIVO},
        {"action": "otra", "reason": MOTIVO},
    ],
)
def test_sin_motivo_o_con_datos_invalidos_se_rechaza_sin_fila(
    client, db, pasarela, admin_token: str, cuerpo: dict
) -> None:
    _, _, _, suscripcion = _suscriptor_manual(client, db, pasarela)
    r = client.patch(
        f"/admin/subscriptions/{suscripcion.id}", json=cuerpo, headers=auth(admin_token)
    )
    assert r.status_code == 422, r.text
    assert _suscripcion(db, suscripcion.id).current_period_end == suscripcion.current_period_end
    assert _filas(db, "subscription.extend") == _filas(db, "subscription.cancel_now") == []


@pytest.mark.parametrize("accion", ["extend", "cancel_at_period_end", "cancel_now"])
def test_una_suscripcion_sin_periodo_vigente_no_se_toca(
    client, db, pasarela, admin_token: str, accion: str
) -> None:
    _, _, _, suscripcion = _suscriptor_automatico(client, db, pasarela)
    db.execute(
        text("UPDATE subscriptions SET current_period_end = now() - interval '1 day' WHERE id = :id"),
        {"id": suscripcion.id},
    )
    db.commit()
    extra = {"days": 5} if accion == "extend" else {}
    r = _accion(client, admin_token, suscripcion.id, accion, **extra)
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "not_in_force")
    assert _filas(db, f"subscription.{accion}") == []
    assert _accion(client, admin_token, uuid.uuid4(), accion, **extra).status_code == 404


@pytest.mark.parametrize("accion", ["extend", "cancel_now"])
def test_con_un_cobro_en_proceso_se_espera(client, db, pasarela, admin_token: str, accion: str) -> None:
    _, user_id, _, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = _avisada(db, pasarela, suscripcion)
    pasarela.estado_del_cobro = "PENDING"
    _correr(db, pasarela, vence - 48 * H)
    assert _pagos(db, user_id)[-1].status == "pending"

    extra = {"days": 5} if accion == "extend" else {}
    r = _accion(client, admin_token, suscripcion.id, accion, **extra)
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "charge_in_progress")
    assert _filas(db, f"subscription.{accion}") == []


# ---------- Cancelar al final del periodo ----------


def test_cancelar_al_final_conserva_el_acceso_y_no_se_vuelve_a_cobrar(
    client, db, pasarela, admin_token: str, outbox
) -> None:
    token, user_id, correo, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = suscripcion.current_period_end
    outbox.clear()

    r = _accion(client, admin_token, suscripcion.id, "cancel_at_period_end")
    assert r.status_code == 200, r.text
    suscripcion = _suscripcion(db, suscripcion.id)
    assert (suscripcion.status, suscripcion.cancel_at_period_end) == ("canceled", True)
    assert suscripcion.current_period_end == vence and suscripcion.next_charge_at is None
    acceso = _acceso(client, token)
    assert (acceso["granted"], acceso["reason"]) == (True, "subscription")

    [fila] = _filas(db, "subscription.cancel_at_period_end")
    assert (fila.reason, fila.before["status"], fila.after["status"]) == (MOTIVO, "active", "canceled")
    assert _asuntos(outbox, correo) == ["Cancelamos la renovación de tu suscripción a Sebasanálisis"]
    assert MOTIVO not in outbox[0].text

    # El job no avisa ni cobra, y al vencer queda vencida.
    for cuando in (vence - 9 * DIA, vence - 48 * H, vence - 24 * H, vence - H):
        reporte = _correr(db, pasarela, cuando)
        assert (reporte.notices, reporte.charges) == (0, 0)
    assert len(pasarela.cobros) == 1
    assert _correr(db, pasarela, vence).expired == 1
    assert _suscripcion(db, suscripcion.id).status == "expired"

    # El cliente todavia la puede reanudar antes del vencimiento: es su decision.
    r = _accion(client, admin_token, suscripcion.id, "cancel_at_period_end")
    assert r.status_code == 409


def test_cancelar_al_final_no_aplica_al_pago_manual_ni_dos_veces(
    client, db, pasarela, admin_token: str
) -> None:
    _, _, _, manual = _suscriptor_manual(client, db, pasarela)
    r = _accion(client, admin_token, manual.id, "cancel_at_period_end")
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "not_automatic")

    _, _, _, automatica = _suscriptor_automatico(client, db, pasarela)
    assert _accion(client, admin_token, automatica.id, "cancel_at_period_end").status_code == 200
    r = _accion(client, admin_token, automatica.id, "cancel_at_period_end")
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "already_canceled")
    assert len(_filas(db, "subscription.cancel_at_period_end")) == 1


# ---------- Cancelar de inmediato ----------


def test_cancelar_de_inmediato_quita_el_acceso_y_no_se_vuelve_a_cobrar(
    client, db, pasarela, admin_token: str, outbox
) -> None:
    token, user_id, correo, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = suscripcion.current_period_end
    assert _tiene_acceso(client, token)
    outbox.clear()

    r = _accion(client, admin_token, suscripcion.id, "cancel_now")
    assert r.status_code == 200, r.text
    assert r.json()["subscription"]["in_force"] is False

    # Sin acceso desde ya, segun has_access.
    assert not _tiene_acceso(client, token)
    assert _acceso(client, token)["reason"] == "expired"
    suscripcion = _suscripcion(db, suscripcion.id)
    assert suscripcion.status == "expired"
    assert suscripcion.current_period_end < vence
    # Ya no hay a que cobrarle.
    assert (suscripcion.payment_source_id, suscripcion.card_last4, suscripcion.next_charge_at) == (
        None,
        None,
        None,
    )
    # No se devolvio nada: el pago sigue aprobado.
    assert [p.status for p in _pagos(db, user_id)] == ["approved"]

    [fila] = _filas(db, "subscription.cancel_now")
    assert (fila.reason, fila.before["payment_source"], fila.after["payment_source"]) == (
        MOTIVO,
        True,
        False,
    )
    assert _asuntos(outbox, correo) == ["Tu suscripción a Sebasanálisis terminó"]
    assert "más cobros" in outbox[0].text and MOTIVO not in outbox[0].text

    # El job no la cobra en ninguna de las horas del cobro.
    for cuando in (vence - 9 * DIA, vence - 48 * H, vence - 24 * H, vence):
        reporte = _correr(db, pasarela, cuando)
        assert (reporte.charges, reporte.notices, _correos(reporte)) == (0, 0, [])
    assert len(pasarela.cobros) == 1

    # Y otra accion sobre ella ya no aplica.
    assert _accion(client, admin_token, suscripcion.id, "cancel_now").status_code == 409


def test_cancelar_de_inmediato_una_de_pago_manual(client, db, pasarela, admin_token: str, outbox) -> None:
    token, user_id, correo, suscripcion = _suscriptor_manual(client, db, pasarela)
    outbox.clear()
    assert _accion(client, admin_token, suscripcion.id, "cancel_now").status_code == 200
    assert not _tiene_acceso(client, token)
    # No tenia renovacion: el correo no habla de cobros que nunca iba a haber.
    assert "más cobros" not in outbox[0].text
    # Puede volver a suscribirse: es un alta nueva.
    r = client.post(
        "/billing/subscriptions", json={"plan_id": str(_mensual(db).id)}, headers=auth(token)
    )
    assert r.status_code == 202, r.text


def test_un_administrador_no_se_deja_sin_acceso(client, db, pasarela, admin_token: str) -> None:
    """Un administrador entra por su rol: cancelar su propia suscripcion no le
    quita la mesa ni la administracion."""
    token, user_id, correo, suscripcion = _suscriptor_manual(client, db, pasarela)
    db.execute(text("UPDATE users SET role = 'admin' WHERE id = :id"), {"id": uuid.UUID(user_id)})
    db.commit()
    token = client.post(
        "/auth/login", json={"email": correo, "password": "clave-segura-123"}
    ).json()["access_token"]

    assert _accion(client, token, suscripcion.id, "cancel_now").status_code == 200
    acceso = _acceso(client, token)
    assert (acceso["granted"], acceso["reason"]) == (True, "admin")
    assert client.get("/admin/subscriptions", headers=auth(token)).status_code == 200


# ---------- Pagos: lista y detalle ----------


def test_la_lista_de_pagos_filtra_en_el_servidor(client, db, pasarela, admin_token: str) -> None:
    token, user_id, correo, _ = _suscriptor_manual(client, db, pasarela)
    rechazado = _abrir_pago(client, db, _cuenta(client, db)[0])
    tx = pasarela.transaccion(rechazado, "DECLINED")
    assert _webhook(client, pasarela.evento(tx)).status_code == 200
    abierto = _abrir_pago(client, db, _cuenta(client, db)[0])

    def lista(**params) -> dict:
        r = client.get("/admin/payments", params=params, headers=auth(admin_token))
        assert r.status_code == 200, r.text
        return r.json()

    assert lista()["total"] == 3
    assert [p["id"] for p in lista(status="declined")["items"]] == [str(rechazado.id)]
    assert [p["id"] for p in lista(status="pending")["items"]] == [str(abierto.id)]
    [aprobado] = lista(query=correo)["items"]
    assert (aprobado["user_email"], aprobado["status"], aprobado["refunded_cents"]) == (
        correo,
        "approved",
        0,
    )
    assert lista(query=rechazado.reference)["items"][0]["id"] == str(rechazado.id)
    assert lista(query=tx)["items"][0]["id"] == str(rechazado.id)
    assert lista(kind="renewal")["total"] == 0
    assert lista(user_id=user_id)["total"] == 1
    assert lista(reversed="true")["total"] == 0
    assert lista(limit=1)["total"] == 3 and len(lista(limit=1)["items"]) == 1


def test_el_detalle_trae_los_eventos_incluidos_los_de_firma_invalida(
    client, db, pasarela, admin_token: str
) -> None:
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tx = pasarela.transaccion(pago, "APPROVED")
    # Primero uno falsificado: no se asocia al pago ni lo mueve.
    falso = pasarela.evento(tx)
    falso["firma"] = "0" * 64
    assert _webhook(client, falso).status_code == 401
    assert _webhook(client, pasarela.evento(tx)).status_code == 200
    # Y uno de otro pago, que no debe aparecer.
    otro = _abrir_pago(client, db, _cuenta(client, db)[0])
    assert _webhook(client, pasarela.evento(pasarela.transaccion(otro, "DECLINED"))).status_code == 200

    r = client.get(f"/admin/payments/{pago.id}", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["payment"]["status"] == "approved"
    eventos = data["events"]
    assert [(e["signature_verified"], e["linked"]) for e in eventos] == [(False, False), (True, True)]
    assert eventos[0]["raw_payload"]["data"]["transaction"]["id"] == tx
    assert data["refunds"] == [] and data["audit"] == []
    assert client.get(f"/admin/payments/{uuid.uuid4()}", headers=auth(admin_token)).status_code == 404


# ---------- Reconsultar ----------


def test_reconsultar_un_pago_pendiente_lo_resuelve_con_la_funcion_del_webhook(
    client, db, pasarela, admin_token: str, outbox
) -> None:
    """El cliente pago y ni el webhook ni la pantalla de regreso llegaron."""
    token, user_id, correo = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tx = pasarela.transaccion(pago, "PENDING")
    assert _webhook(client, pasarela.evento(tx)).status_code == 200
    assert not _tiene_acceso(client, token)
    pasarela.resolver(tx, "APPROVED")
    outbox.clear()

    r = client.post(
        f"/admin/payments/{pago.id}/requery", json={"reason": MOTIVO}, headers=auth(admin_token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["payment"]["status"] == "approved"
    assert _tiene_acceso(client, token)
    [fila] = _filas(db, "payment.requery")
    assert (fila.target_id, fila.reason, fila.before, fila.after) == (
        str(pago.id),
        MOTIVO,
        {"status": "pending"},
        {"status": "approved", "provider_status": "approved"},
    )
    # Los mismos correos que si hubiera llegado el webhook.
    assert sorted(_asuntos(outbox, correo)) == [
        "Recibo de tu pago en Sebasanálisis",
        "Tu suscripción a Sebasanálisis está activa",
    ]


def test_reconsultar_un_pago_ya_resuelto_no_concede_otro_periodo(
    client, db, pasarela, admin_token: str, outbox
) -> None:
    token, user_id, correo, suscripcion = _suscriptor_manual(client, db, pasarela)
    [pago] = _pagos(db, user_id)
    vence = suscripcion.current_period_end
    outbox.clear()

    for _ in range(2):
        r = client.post(
            f"/admin/payments/{pago.id}/requery", json={"reason": MOTIVO}, headers=auth(admin_token)
        )
        assert r.status_code == 200, r.text
    assert _suscripcion(db, suscripcion.id).current_period_end == vence
    assert [p.status for p in _pagos(db, user_id)] == ["approved"]
    assert outbox == []
    # Cada reconsulta queda en la bitacora, aunque no haya cambiado nada.
    filas = _filas(db, "payment.requery")
    assert [(f.before, f.after["status"]) for f in filas] == [({"status": "approved"}, "approved")] * 2


@pytest.mark.parametrize("cuerpo", [{}, {"reason": ""}, {"reason": "no"}])
def test_reconsultar_sin_motivo_se_rechaza_sin_fila(client, db, pasarela, admin_token: str, cuerpo) -> None:
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    pasarela.transaccion(pago, "APPROVED")
    r = client.post(f"/admin/payments/{pago.id}/requery", json=cuerpo, headers=auth(admin_token))
    assert r.status_code == 422
    assert _filas(db, "payment.requery") == []


def test_reconsultar_lo_que_no_se_puede(client, db, pasarela, admin_token: str) -> None:
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    url = f"/admin/payments/{pago.id}/requery"
    body = {"reason": MOTIVO}

    # Sin transaccion en el proveedor: nada que preguntar.
    r = client.post(url, json=body, headers=auth(admin_token))
    assert r.status_code == 409

    tx = pasarela.transaccion(pago, "PENDING")
    assert _webhook(client, pasarela.evento(tx)).status_code == 200
    pasarela.caido = True
    assert client.post(url, json=body, headers=auth(admin_token)).status_code == 502
    pasarela.caido = False
    del pasarela.transactions[tx]
    assert client.post(url, json=body, headers=auth(admin_token)).status_code == 409
    assert _filas(db, "payment.requery") == []


def test_reconsultar_sin_pasarela(client, db, admin_token: str) -> None:
    """El cliente de los tests arranca sin pasarela."""
    token, user_id, _ = _cuenta(client, db)
    plan = _mensual(db)
    db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, plan_id, provider, status, price_cents, currency) "
            "VALUES (:s, :u, :p, 'pasarela', 'pending', :c, 'COP')"
        ),
        {"s": uuid.uuid4(), "u": uuid.UUID(user_id), "p": plan.id, "c": PRECIO},
    )
    pago_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO payments (id, user_id, plan_id, provider, reference, kind, amount_cents, "
            "currency, status, provider_transaction_id) VALUES (:id, :u, :p, 'pasarela', :r, "
            "'initial', :c, 'COP', 'pending', 'tx-1')"
        ),
        {"id": pago_id, "u": uuid.UUID(user_id), "p": plan.id, "r": f"SA-{pago_id.hex}", "c": PRECIO},
    )
    db.commit()
    r = client.post(
        f"/admin/payments/{pago_id}/requery", json={"reason": MOTIVO}, headers=auth(admin_token)
    )
    assert r.status_code == 503


# ---------- Un pago aprobado que el proveedor anula despues ----------


def test_un_pago_anulado_despues_quita_el_acceso_en_el_acto(
    client, db, pasarela, outbox
) -> None:
    """Decidido el 2026-10-14: la anulacion llega como evento, la reconsulta la
    confirma y el periodo que habia comprado se retira."""
    token, user_id, correo = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tx = _aprobar(client, pasarela, pago)
    assert _tiene_acceso(client, token)
    outbox.clear()

    pasarela.resolver(tx, "VOIDED")
    assert _webhook(client, pasarela.evento(tx, timestamp=1_760_000_500)).status_code == 200

    assert not _tiene_acceso(client, token)
    assert _acceso(client, token)["reason"] == "expired"
    [pago] = _pagos(db, user_id)
    assert (pago.status, pago.reversed_at is not None) == ("voided", True)
    assert "el acceso terminó" in pago.reversal_note
    [suscripcion] = _suscripciones(db, user_id)
    assert suscripcion.status == "expired"
    assert suscripcion.current_period_end == pago.period_start
    # La anulacion la hizo el comercio en el panel: no sale correo.
    assert outbox == []
    # El mismo evento otra vez, o reconsultar, no hace nada mas.
    assert _webhook(client, pasarela.evento(tx, timestamp=1_760_000_500)).json()["status"] == "duplicate"
    assert _webhook(client, pasarela.evento(tx, timestamp=1_760_000_900)).status_code == 200
    assert _suscripciones(db, user_id)[0].current_period_end == suscripcion.current_period_end


def test_una_anulacion_que_llega_por_reconsultar_deja_fila(
    client, db, pasarela, admin_token: str
) -> None:
    token, user_id, _, _ = _suscriptor_manual(client, db, pasarela)
    [pago] = _pagos(db, user_id)
    pasarela.resolver(pago.provider_transaction_id, "VOIDED")

    r = client.post(
        f"/admin/payments/{pago.id}/requery", json={"reason": MOTIVO}, headers=auth(admin_token)
    )
    assert r.status_code == 200, r.text
    data = r.json()["payment"]
    assert data["status"] == "voided" and data["reversed_at"] is not None
    assert not _tiene_acceso(client, token)
    [fila] = _filas(db, "payment.requery")
    assert (fila.before, fila.after) == (
        {"status": "approved"},
        {"status": "voided", "provider_status": "voided"},
    )
    r = client.get("/admin/payments", params={"reversed": "true"}, headers=auth(admin_token))
    assert [p["id"] for p in r.json()["items"]] == [str(pago.id)]


def test_anular_un_pago_con_un_periodo_posterior_no_toca_nada(client, db, pasarela) -> None:
    """El periodo que compro ya no es el ultimo: retirarlo solo dejaria un
    hueco. Queda la nota para revisarlo a mano."""
    token, user_id, _, suscripcion = _suscriptor_manual(client, db, pasarela)
    primero = _pagos(db, user_id)[0]
    segundo = _abrir_pago(client, db, token)
    _aprobar(client, pasarela, segundo, timestamp=1_760_000_100)
    vence = _suscripcion(db, suscripcion.id).current_period_end
    assert vence == _pagos(db, user_id)[1].period_end

    pasarela.resolver(primero.provider_transaction_id, "VOIDED")
    assert _webhook(client, pasarela.evento(primero.provider_transaction_id, timestamp=1_760_000_200)).status_code == 200

    primero = _pagos(db, user_id)[0]
    assert primero.status == "voided" and "revisarlo a mano" in primero.reversal_note
    assert _suscripcion(db, suscripcion.id).current_period_end == vence
    assert _tiene_acceso(client, token)


def test_anular_una_renovacion_cobrada_antes_del_vencimiento(client, db, pasarela) -> None:
    """El cobro de renovacion sale 48 h antes. Si se anula antes de que empiece
    el periodo que compro, el anterior sigue, y la renovacion se cancela para
    que el job no le vuelva a cobrar sin que alguien lo decida."""
    token, user_id, _, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = _avisada(db, pasarela, suscripcion)
    assert _correr(db, pasarela, vence - 48 * H).approved == 1
    renovacion = _pagos(db, user_id)[1]
    assert renovacion.kind == "renewal"

    pasarela.resolver(renovacion.provider_transaction_id, "VOIDED")
    assert _webhook(client, pasarela.evento(renovacion.provider_transaction_id, timestamp=1_760_000_300)).status_code == 200

    suscripcion = _suscripcion(db, suscripcion.id)
    assert suscripcion.current_period_end == vence
    assert (suscripcion.status, suscripcion.cancel_at_period_end) == ("canceled", True)
    assert _tiene_acceso(client, token)
    for cuando in (vence - 24 * H, vence - H):
        assert _correr(db, pasarela, cuando).charges == 0
    assert len(pasarela.cobros) == 2
    assert _correr(db, pasarela, vence).expired == 1


def test_una_anulacion_de_otra_transaccion_no_toca_el_pago(client, db, pasarela) -> None:
    """Solo la transaccion que lo aprobo puede anularlo."""
    token, user_id, _, suscripcion = _suscriptor_manual(client, db, pasarela)
    [pago] = _pagos(db, user_id)
    otra = pasarela.transaccion(pago, "VOIDED")
    assert _webhook(client, pasarela.evento(otra)).status_code == 200
    assert _pagos(db, user_id)[0].status == "approved"
    assert _tiene_acceso(client, token)


# ---------- Reembolsos registrados ----------


def _reembolso(client, admin_token: str, pago_id, **cambios):
    body = {
        "amount_cents": 4_000_000,
        "refunded_at": (datetime.now(UTC) - H).isoformat(),
        "provider_refund_id": "rf-123",
        "reason": MOTIVO,
        **cambios,
    }
    return client.post(f"/admin/payments/{pago_id}/refunds", json=body, headers=auth(admin_token))


def test_registrar_un_reembolso_deja_fila_y_no_toca_el_acceso(
    client, db, pasarela, admin_token: str, outbox
) -> None:
    token, user_id, _, suscripcion = _suscriptor_manual(client, db, pasarela)
    [pago] = _pagos(db, user_id)
    outbox.clear()

    r = _reembolso(client, admin_token, pago.id)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["payment"]["refunded_cents"] == 4_000_000
    assert data["payment"]["status"] == "approved"
    [registro] = data["refunds"]
    assert (registro["amount_cents"], registro["currency"], registro["provider_refund_id"]) == (
        4_000_000,
        "COP",
        "rf-123",
    )
    assert [a["action"] for a in data["audit"]] == ["payment.refund.record"]
    [fila] = _filas(db, "payment.refund.record")
    assert (fila.reason, fila.after["refunded_cents"]) == (MOTIVO, 4_000_000)
    # Un registro, no un movimiento.
    assert _tiene_acceso(client, token)
    assert _suscripcion(db, suscripcion.id).current_period_end == suscripcion.current_period_end
    assert outbox == []

    # El resto, hasta completar lo cobrado; mas no.
    assert _reembolso(client, admin_token, pago.id, amount_cents=PRECIO - 4_000_000).status_code == 201
    r = _reembolso(client, admin_token, pago.id, amount_cents=1)
    assert r.status_code == 409
    assert len(_filas(db, "payment.refund.record")) == 2
    r = client.get("/admin/payments", params={"refunded": "true"}, headers=auth(admin_token))
    assert [p["refunded_cents"] for p in r.json()["items"]] == [PRECIO]


@pytest.mark.parametrize(
    "cambios",
    [
        {"reason": ""},
        {"reason": "no"},
        {"amount_cents": 0},
        {"refunded_at": (datetime.now(UTC) + DIA).isoformat()},
    ],
)
def test_un_reembolso_sin_motivo_o_invalido_se_rechaza_sin_fila(
    client, db, pasarela, admin_token: str, cambios: dict
) -> None:
    _, user_id, _, _ = _suscriptor_manual(client, db, pasarela)
    [pago] = _pagos(db, user_id)
    assert _reembolso(client, admin_token, pago.id, **cambios).status_code == 422
    assert _filas(db, "payment.refund.record") == []
    assert db.scalar(select(func.count()).select_from(PaymentRefund)) == 0


def test_solo_se_reembolsa_un_pago_aprobado(client, db, pasarela, admin_token: str) -> None:
    pago = _abrir_pago(client, db, _cuenta(client, db)[0])
    assert _reembolso(client, admin_token, pago.id).status_code == 409
    assert _reembolso(client, admin_token, uuid.uuid4()).status_code == 404


# ---------- Desde el detalle de la cuenta ----------


def test_el_detalle_de_la_cuenta_muestra_las_acciones_sobre_su_suscripcion(
    client, db, pasarela, admin_token: str
) -> None:
    _, user_id, _, suscripcion = _suscriptor_manual(client, db, pasarela)
    [pago] = _pagos(db, user_id)
    assert _accion(client, admin_token, suscripcion.id, "extend", days=2).status_code == 200
    assert _reembolso(client, admin_token, pago.id).status_code == 201
    # Una accion sobre otra cuenta no aparece.
    _, _, _, otra = _suscriptor_manual(client, db, pasarela)
    assert _accion(client, admin_token, otra.id, "extend", days=2).status_code == 200

    r = client.get(f"/admin/users/{user_id}", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert [a["action"] for a in data["audit"]] == ["payment.refund.record", "subscription.extend"]
    assert data["payments"][0]["refunded_cents"] == 4_000_000
    assert data["subscription"]["id"] == str(suscripcion.id)


def test_los_eventos_quedan_aunque_se_elimine_la_cuenta(client, db, pasarela, admin_token: str) -> None:
    """El detalle del pago sigue sirviendo sin la cuenta: sus eventos ya
    vienen reducidos (§3.15)."""
    token, user_id, _, _ = _suscriptor_manual(client, db, pasarela)
    [pago] = _pagos(db, user_id)
    r = client.request(
        "DELETE", "/auth/me", json={"password": "clave-segura-123"}, headers=auth(token)
    )
    assert r.status_code == 204, r.text
    r = client.get(f"/admin/payments/{pago.id}", headers=auth(admin_token))
    assert r.status_code == 200
    data = r.json()
    assert (data["payment"]["user_id"], data["payment"]["user_email"]) == (None, None)
    assert [e["linked"] for e in data["events"]] == [True]
    assert db.scalar(select(func.count()).select_from(PaymentEvent)) == 1
    assert db.get(Payment, pago.id) is not None
