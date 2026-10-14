"""Traslado del precio de un plan a sus suscripciones vigentes (§4.10 y §10 n.º 5).

Decidido el 2026-10-14: una subida se cobra 30 dias despues de que el aviso le
llego a cada cliente; una bajada aplica ya; un cupon sigue descontando sobre el
precio nuevo; no alcanza a las canceladas; se puede cancelar mientras no se haya
aplicado.

El job (`run_renewals` y `send_notices`) se llama directo con el `now` que cada
caso necesita.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.core.email import EmailMessage, FakeEmailSender
from app.core.price_changes import apply_due, send_notices
from app.models import AdminAuditLog, Payment, Plan, SubscriptionPriceChange
from tests.api.conftest import auth
from tests.api.test_admin_payments import MOTIVO, _accion, _suscripcion, _suscriptor_manual
from tests.api.test_billing import _cupon, _mensual
from tests.api.test_renewals import _avisada, _correr, _suscriptor_automatico
from tests.api.test_subscriptions import PRECIO, _pagos, _suscribir

NUEVO = 12_000_000  # 120.000 COP
MENOR = 8_000_000  # 80.000 COP
H = timedelta(hours=1)
DIA = timedelta(days=1)


@pytest.fixture(autouse=True)
def limpio(db) -> Iterator[None]:
    """Cada test empieza sin suscripciones ni traslados de otros, y deja el plan
    mensual con su precio: lo usan todos los demas tests."""
    for tabla in (
        "subscription_price_changes",
        "price_changes",
        "payment_refunds",
        "payment_events",
        "payments",
        "coupon_redemptions",
        "subscriptions",
    ):
        db.execute(text(f"DELETE FROM {tabla}"))
    db.execute(text("DELETE FROM admin_audit_log WHERE target_type = 'plan'"))
    db.commit()
    yield
    db.rollback()
    db.execute(text("UPDATE plans SET price_cents = :p WHERE code = 'mensual'"), {"p": PRECIO})
    db.commit()


# ---------- Ayudas ----------


def _precio_del_plan(db, cents: int) -> Plan:
    plan = _mensual(db)
    db.execute(text("UPDATE plans SET price_cents = :p WHERE id = :id"), {"p": cents, "id": plan.id})
    db.commit()
    db.expire_all()
    return _mensual(db)


def _trasladar(client, admin_token: str, plan_id, reason: str = MOTIVO):
    return client.post(
        f"/admin/plans/{plan_id}/price-transfer", json={"reason": reason}, headers=auth(admin_token)
    )


def _filas(db, subscription_id=None) -> list[SubscriptionPriceChange]:
    db.expire_all()
    query = select(SubscriptionPriceChange).order_by(SubscriptionPriceChange.created_at)
    if subscription_id is not None:
        query = query.where(SubscriptionPriceChange.subscription_id == subscription_id)
    return list(db.scalars(query))


def _avisar(db, cuando: datetime, sender=None):
    sender = sender or FakeEmailSender()
    reporte = send_notices(db, sender, cuando)
    db.expire_all()
    return reporte, sender


class _Caido:
    """Un servidor de correo que no responde."""

    def send(self, message: EmailMessage) -> None:
        raise ConnectionError("sin correo")


# ---------- Solo administradores ----------


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [
        ("GET", "/admin/plans/{plan}/price-transfer"),
        ("POST", "/admin/plans/{plan}/price-transfer"),
        ("GET", "/admin/price-changes"),
        ("POST", "/admin/price-changes/{change}/cancel"),
    ],
)
def test_solo_un_administrador(client, db, user_token: str, metodo: str, ruta: str) -> None:
    url = ruta.replace("{plan}", str(_mensual(db).id)).replace("{change}", str(uuid.uuid4()))
    body = {"reason": MOTIVO} if metodo == "POST" else None
    assert client.request(metodo, url, json=body, headers=auth(user_token)).status_code == 403
    assert client.request(metodo, url, json=body).status_code == 401


# ---------- Registrar ----------


def test_registrar_un_traslado_alcanza_a_las_vigentes_del_plan_y_deja_fila(
    client, db, wompi, admin_token: str
) -> None:
    _, _, _, manual = _suscriptor_manual(client, db, wompi)
    _, _, _, automatica = _suscriptor_automatico(client, db, wompi)
    # Una cancelada y una vencida no entran.
    _, _, _, cancelada = _suscriptor_automatico(client, db, wompi)
    assert _accion(client, admin_token, cancelada.id, "cancel_at_period_end").status_code == 200
    _, _, _, vencida = _suscriptor_manual(client, db, wompi)
    assert _accion(client, admin_token, vencida.id, "cancel_now").status_code == 200
    plan = _precio_del_plan(db, NUEVO)

    r = client.get(f"/admin/plans/{plan.id}/price-transfer", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    assert (r.json()["increases"], r.json()["decreases"], r.json()["open_change"]) == (2, 0, None)

    r = _trasladar(client, admin_token, plan.id)
    assert r.status_code == 201, r.text
    data = r.json()
    assert (data["new_price_cents"], data["total"], data["applied"], data["waiting_notice"]) == (
        NUEVO,
        2,
        0,
        2,
    )
    assert {f.subscription_id for f in _filas(db)} == {manual.id, automatica.id}
    # Hasta que salga el aviso, nada cambia.
    assert _suscripcion(db, manual.id).price_cents == PRECIO
    assert all(f.effective_at is None for f in _filas(db))

    [fila] = db.scalars(
        select(AdminAuditLog).where(AdminAuditLog.action == "plan.price.transfer")
    ).all()
    assert (fila.reason, fila.after["increases"], fila.after["new_price_cents"]) == (
        MOTIVO,
        2,
        NUEVO,
    )

    # Otro traslado del mismo plan, con este en curso, no.
    r = _trasladar(client, admin_token, plan.id)
    assert r.status_code == 409
    r = client.get(f"/admin/plans/{plan.id}/price-transfer", headers=auth(admin_token))
    assert r.json()["open_change"]["id"] == data["id"]


@pytest.mark.parametrize("motivo", ["", "no"])
def test_sin_motivo_no_se_registra(client, db, wompi, admin_token: str, motivo: str) -> None:
    _suscriptor_manual(client, db, wompi)
    plan = _precio_del_plan(db, NUEVO)
    assert _trasladar(client, admin_token, plan.id, motivo).status_code == 422
    assert _filas(db) == []
    assert db.scalars(select(AdminAuditLog).where(AdminAuditLog.target_type == "plan")).all() == []


def test_sin_suscripciones_con_otro_precio_no_hay_traslado(client, db, wompi, admin_token: str) -> None:
    _suscriptor_manual(client, db, wompi)
    r = _trasladar(client, admin_token, _mensual(db).id)
    assert r.status_code == 409
    assert client.post(
        f"/admin/plans/{uuid.uuid4()}/price-transfer",
        json={"reason": MOTIVO},
        headers=auth(admin_token),
    ).status_code == 404


# ---------- Subida: aviso y plazo ----------


def test_el_aviso_de_una_subida_fija_la_fecha_treinta_dias_despues(
    client, db, wompi, admin_token: str
) -> None:
    token, _, correo, suscripcion = _suscriptor_automatico(client, db, wompi)
    plan = _precio_del_plan(db, NUEVO)
    assert _trasladar(client, admin_token, plan.id).status_code == 201

    ahora = datetime.now(UTC)
    reporte, sender = _avisar(db, ahora)
    assert reporte.sent == 1
    [aviso] = sender.sent
    assert aviso.to == correo
    assert aviso.subject == "Aviso: cambia el precio de tu suscripción a Sebasanálisis"
    assert "100.000 COP" in aviso.text and "120.000 COP" in aviso.text
    assert "cancelar la renovación" in aviso.text
    [fila] = _filas(db)
    assert fila.notice_sent_at == ahora and fila.effective_at == ahora + 30 * DIA

    # Una segunda corrida no lo repite.
    assert _avisar(db, ahora + H)[0].sent == 0

    # El cliente lo ve en su cuenta.
    r = client.get("/billing/subscription", headers=auth(token))
    assert r.json()["price_change"] == {
        "new_price_cents": NUEVO,
        "effective_at": r.json()["price_change"]["effective_at"],
    }
    assert datetime.fromisoformat(r.json()["price_change"]["effective_at"]) == ahora + 30 * DIA


def test_si_el_aviso_no_sale_no_corre_el_plazo_ni_cambia_el_precio(
    client, db, wompi, admin_token: str
) -> None:
    _, _, _, suscripcion = _suscriptor_automatico(client, db, wompi)
    plan = _precio_del_plan(db, NUEVO)
    assert _trasladar(client, admin_token, plan.id).status_code == 201

    ahora = datetime.now(UTC)
    reporte, _ = _avisar(db, ahora, _Caido())
    assert (reporte.sent, reporte.failed) == (0, 1)
    [fila] = _filas(db)
    assert (fila.notice_sent_at, fila.effective_at) == (None, None)
    # Ni con el tiempo: el precio nuevo no corre sin aviso.
    assert apply_due(db, ahora + 400 * DIA) == 0
    db.commit()
    assert _suscripcion(db, suscripcion.id).price_cents == PRECIO

    # Cuando el correo vuelve, sale y empieza a contar desde ese envio.
    reporte, sender = _avisar(db, ahora + DIA)
    assert reporte.sent == 1 and _filas(db)[0].effective_at == ahora + 31 * DIA


def test_la_subida_se_cobra_desde_su_fecha_y_el_cupon_sigue_descontando(
    client, db, wompi, admin_token: str
) -> None:
    cupon = _cupon(db, value=20, duration="forever")
    _, user_id, correo, suscripcion = _suscriptor_automatico(client, db, wompi, codigo=cupon.code)
    plan = _precio_del_plan(db, NUEVO)
    assert _trasladar(client, admin_token, plan.id).status_code == 201
    aviso = datetime.now(UTC)
    _avisar(db, aviso)
    efectiva = aviso + 30 * DIA

    # Un cobro antes de la fecha va con el precio viejo; uno despues, con el
    # nuevo, y el 20 % se descuenta del nuevo.
    vence = _avisada(db, wompi, suscripcion)
    cobro = vence - 48 * H
    reporte = _correr(db, wompi, cobro)
    assert reporte.charges == 1
    esperado = PRECIO if cobro < efectiva else NUEVO
    assert wompi.cobros[-1]["amount_in_cents"] == esperado * 80 // 100

    if cobro < efectiva:
        # El periodo siguiente ya cae despues: su aviso y su cobro son con el nuevo.
        suscripcion = _suscripcion(db, suscripcion.id)
        vence = suscripcion.current_period_end
        reporte = _correr(db, wompi, vence - 9 * DIA)
        [aviso_cobro] = [m for m in reporte.emails if m.to == correo]
        assert "96.000 COP" in aviso_cobro.text
        assert _correr(db, wompi, vence - 48 * H).charges == 1
        assert wompi.cobros[-1]["amount_in_cents"] == NUEVO * 80 // 100
    assert _suscripcion(db, suscripcion.id).price_cents == NUEVO
    assert _filas(db)[0].applied_at is not None


def test_en_pago_manual_el_precio_nuevo_corre_para_el_pago_siguiente(
    client, db, wompi, admin_token: str
) -> None:
    token, user_id, _, suscripcion = _suscriptor_manual(client, db, wompi)
    plan = _precio_del_plan(db, NUEVO)
    assert _trasladar(client, admin_token, plan.id).status_code == 201
    _avisar(db, datetime.now(UTC))

    # Antes de la fecha, el pago del periodo siguiente es con el precio viejo.
    r = _suscribir(client, token, plan.id)
    assert r.status_code == 202, r.text
    assert r.json()["total_cents"] == PRECIO

    # Con la fecha ya pasada, con el nuevo.
    db.execute(
        text("UPDATE subscription_price_changes SET effective_at = now() - interval '1 hour'")
    )
    db.commit()
    r = _suscribir(client, token, plan.id)
    assert r.json()["total_cents"] == NUEVO
    assert _suscripcion(db, suscripcion.id).price_cents == NUEVO


def test_una_cancelada_espera_su_aviso_y_si_reanuda_lo_recibe(
    client, db, wompi, admin_token: str
) -> None:
    token, _, correo, suscripcion = _suscriptor_automatico(client, db, wompi)
    plan = _precio_del_plan(db, NUEVO)
    assert _trasladar(client, admin_token, plan.id).status_code == 201
    assert client.post("/billing/subscription/cancel", headers=auth(token)).status_code == 200

    reporte, sender = _avisar(db, datetime.now(UTC))
    assert (reporte.sent, sender.sent) == (0, [])
    assert client.post("/billing/subscription/resume", headers=auth(token)).status_code == 200
    reporte, sender = _avisar(db, datetime.now(UTC))
    assert [m.to for m in sender.sent] == [correo]


def test_una_subida_de_una_suscripcion_que_vencio_sale_del_traslado(
    client, db, wompi, admin_token: str
) -> None:
    _, _, _, suscripcion = _suscriptor_manual(client, db, wompi)
    plan = _precio_del_plan(db, NUEVO)
    r = _trasladar(client, admin_token, plan.id)
    vence = _suscripcion(db, suscripcion.id).current_period_end

    reporte, sender = _avisar(db, vence + H)
    assert (reporte.closed, sender.sent) == (1, [])
    [fila] = _filas(db)
    assert fila.canceled_at is not None
    # Con eso el plan ya no tiene un traslado en curso.
    r = client.get(f"/admin/plans/{plan.id}/price-transfer", headers=auth(admin_token))
    assert r.json()["open_change"] is None


def test_los_avisos_salen_por_lotes(client, db, wompi, admin_token: str) -> None:
    for _ in range(3):
        _suscriptor_manual(client, db, wompi)
    plan = _precio_del_plan(db, NUEVO)
    assert _trasladar(client, admin_token, plan.id).status_code == 201
    ahora = datetime.now(UTC)
    assert send_notices(db, FakeEmailSender(), ahora, limit=2).sent == 2
    assert send_notices(db, FakeEmailSender(), ahora, limit=2).sent == 1


# ---------- Bajada ----------


def test_una_bajada_aplica_ya_y_avisa(client, db, wompi, admin_token: str) -> None:
    _, user_id, correo, suscripcion = _suscriptor_automatico(client, db, wompi)
    plan = _precio_del_plan(db, MENOR)
    r = _trasladar(client, admin_token, plan.id)
    assert r.status_code == 201, r.text
    assert (r.json()["applied"], r.json()["waiting_notice"]) == (1, 1)
    assert _suscripcion(db, suscripcion.id).price_cents == MENOR

    reporte, sender = _avisar(db, datetime.now(UTC))
    [aviso] = sender.sent
    assert aviso.subject == "Bajó el precio de tu suscripción a Sebasanálisis"
    assert "80.000 COP" in aviso.text

    # El proximo cobro ya es con el precio menor.
    vence = _avisada(db, wompi, suscripcion)
    assert _correr(db, wompi, vence - 48 * H).charges == 1
    assert wompi.cobros[-1]["amount_in_cents"] == MENOR
    # Una bajada ya aplicada no deja el traslado en curso.
    r = client.get(f"/admin/plans/{plan.id}/price-transfer", headers=auth(admin_token))
    assert r.json()["open_change"] is None


# ---------- Cancelar ----------


def test_cancelar_un_traslado_conserva_el_precio_y_avisa_a_quien_ya_sabia(
    client, db, wompi, admin_token: str
) -> None:
    _, _, avisado, suscripcion_a = _suscriptor_automatico(client, db, wompi)
    plan = _precio_del_plan(db, NUEVO)
    change = _trasladar(client, admin_token, plan.id).json()
    ahora = datetime.now(UTC)
    _avisar(db, ahora)
    # Una cuenta que se suscribe despues no entra: ya paga el precio nuevo.

    url = f"/admin/price-changes/{change['id']}/cancel"
    assert client.post(url, json={"reason": "no"}, headers=auth(admin_token)).status_code == 422
    r = client.post(url, json={"reason": MOTIVO}, headers=auth(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["canceled_at"] is not None and r.json()["canceled"] == 1
    [fila] = db.scalars(
        select(AdminAuditLog).where(AdminAuditLog.action == "plan.price.transfer.cancel")
    ).all()
    assert fila.reason == MOTIVO

    reporte, sender = _avisar(db, ahora + H)
    [aviso] = sender.sent
    assert (aviso.to, aviso.subject) == (
        avisado,
        "El precio de tu suscripción a Sebasanálisis no cambia",
    )
    assert _avisar(db, ahora + 2 * H)[1].sent == []
    # Ni con el tiempo cambia el precio.
    _correr(db, wompi, ahora + 31 * DIA)
    assert _suscripcion(db, suscripcion_a.id).price_cents == PRECIO

    # No se cancela dos veces, y el plan admite otro traslado.
    assert client.post(url, json={"reason": MOTIVO}, headers=auth(admin_token)).status_code == 409
    assert _trasladar(client, admin_token, plan.id).status_code == 201
    assert client.post(
        f"/admin/price-changes/{uuid.uuid4()}/cancel",
        json={"reason": MOTIVO},
        headers=auth(admin_token),
    ).status_code == 404


def test_cancelar_antes_del_aviso_no_le_escribe_a_nadie(client, db, wompi, admin_token: str) -> None:
    _suscriptor_manual(client, db, wompi)
    plan = _precio_del_plan(db, NUEVO)
    change = _trasladar(client, admin_token, plan.id).json()
    r = client.post(
        f"/admin/price-changes/{change['id']}/cancel",
        json={"reason": MOTIVO},
        headers=auth(admin_token),
    )
    assert r.status_code == 200
    assert _avisar(db, datetime.now(UTC))[1].sent == []


def test_el_historial_de_traslados(client, db, wompi, admin_token: str) -> None:
    _suscriptor_manual(client, db, wompi)
    plan = _precio_del_plan(db, NUEVO)
    assert _trasladar(client, admin_token, plan.id).status_code == 201
    r = client.get(
        "/admin/price-changes", params={"plan_id": str(plan.id)}, headers=auth(admin_token)
    )
    assert r.status_code == 200
    [item] = r.json()["items"]
    assert (item["plan_name"], item["reason"], item["total"]) == ("Acceso Mensual", MOTIVO, 1)


def test_el_traslado_no_mueve_ningun_pago(client, db, wompi, admin_token: str) -> None:
    _, user_id, _, _ = _suscriptor_manual(client, db, wompi)
    antes = [(p.id, p.status, p.amount_cents) for p in _pagos(db, user_id)]
    plan = _precio_del_plan(db, MENOR)
    assert _trasladar(client, admin_token, plan.id).status_code == 201
    _avisar(db, datetime.now(UTC))
    assert [(p.id, p.status, p.amount_cents) for p in _pagos(db, user_id)] == antes
    assert db.scalar(select(Payment).where(Payment.status == "pending")) is None
