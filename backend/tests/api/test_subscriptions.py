"""Alta con pago manual, webhook y reconsulta (§3.4 y §3.9 de la Fase 4).

El proveedor es el `WompiProvider` de verdad, con llaves de prueba y un
transporte HTTP que responde desde un diccionario: ningun test sale a la red, y
aun asi pasan por la verificacion de firma y la lectura de respuestas reales.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.billing.periods import add_interval
from app.models import (
    Coupon,
    CouponRedemption,
    Payment,
    PaymentEvent,
    Plan,
    Subscription,
)
from app.payments.base import get_payment_provider
from app.payments.fake import FAKE_SIGNATURE, FAKE_SIGNATURE_HEADER, FakePaymentProvider
from app.payments.wompi import integrity_signature
from tests.api.conftest import auth, register_raw
from tests.api.test_billing import _cupon, _mensual, _plan
from tests.api.wompi_double import INTEGRITY_SECRET, Wompi

PRECIO = 10_000_000  # 100.000 COP en centavos


# ---------- Ayudas ----------


def _cuenta(client: TestClient, db, *, verificada: bool = True) -> tuple[str, str, str]:
    """Una cuenta como la de un cliente nuevo: consentimientos aceptados y sin
    acceso. Devuelve (token, id, correo)."""
    email = f"pago-{uuid.uuid4().hex[:12]}@ejemplo.com"
    registro = register_raw(client, email)
    user_id = registro["user"]["id"]
    if verificada:
        db.execute(text("UPDATE users SET email_verified = true WHERE id = :id"), {"id": user_id})
        db.commit()
    return registro["access_token"], user_id, email


def _suscribir(client: TestClient, token: str, plan_id, codigo: str | None = None, **extra):
    body = {"plan_id": str(plan_id), **extra}
    if codigo is not None:
        body["coupon_code"] = codigo
    return client.post("/billing/subscriptions", json=body, headers=auth(token))


def _abrir_pago(client: TestClient, db, token: str, plan: Plan | None = None, codigo=None) -> Payment:
    r = _suscribir(client, token, (plan or _mensual(db)).id, codigo)
    assert r.status_code == 202, r.text
    return db.get(Payment, uuid.UUID(r.json()["payment_id"]))


def _webhook(client: TestClient, evento: dict, **headers):
    return client.post(
        "/webhooks/wompi",
        content=json.dumps(evento).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Event-Checksum": evento["signature"]["checksum"] or "",
            **headers,
        },
    )


def _aprobar(client: TestClient, wompi: Wompi, payment: Payment, timestamp: int = 1_760_000_000):
    tx_id = wompi.transaccion(payment, "APPROVED")
    r = _webhook(client, wompi.evento(tx_id, timestamp=timestamp))
    assert r.status_code == 200, r.text
    return tx_id


def _tiene_acceso(client: TestClient, token: str) -> bool:
    r = client.get("/sessions", headers=auth(token))
    assert r.status_code in (200, 403), r.text
    return r.status_code == 200


def _suscripciones(db, user_id: str) -> list[Subscription]:
    db.expire_all()
    return list(db.scalars(select(Subscription).where(Subscription.user_id == uuid.UUID(user_id))))


def _pagos(db, user_id: str) -> list[Payment]:
    db.expire_all()
    return list(
        db.scalars(
            select(Payment).where(Payment.user_id == uuid.UUID(user_id)).order_by(Payment.created_at)
        )
    )


def _eventos(db) -> int:
    return db.scalar(select(func.count()).select_from(PaymentEvent))


def _asuntos(outbox: list, correo: str) -> list[str]:
    return [m.subject for m in outbox if m.to == correo]


# ---------- POST /billing/subscriptions ----------


def test_abrir_el_pago_deja_todo_pendiente_y_no_da_acceso(client, db, wompi) -> None:
    token, user_id, _ = _cuenta(client, db)
    r = _suscribir(client, token, _mensual(db).id)
    assert r.status_code == 202, r.text
    data = r.json()
    assert (data["subtotal_cents"], data["discount_cents"], data["total_cents"]) == (PRECIO, 0, PRECIO)
    assert data["currency"] == "COP"

    [suscripcion] = _suscripciones(db, user_id)
    assert (suscripcion.status, suscripcion.renewal_mode, suscripcion.provider) == (
        "pending",
        "manual",
        "wompi",
    )
    assert (suscripcion.price_cents, suscripcion.currency) == (PRECIO, "COP")
    assert suscripcion.current_period_end is None
    # No se tokeniza nada en el pago manual.
    assert (suscripcion.payment_source_id, suscripcion.card_brand, suscripcion.card_last4) == (
        None,
        None,
        None,
    )
    [pago] = _pagos(db, user_id)
    assert (pago.status, pago.kind, pago.amount_cents, pago.currency) == ("pending", "initial", PRECIO, "COP")
    assert str(pago.id) == data["payment_id"]
    assert not _tiene_acceso(client, token)

    # El enlace lleva a Wompi la referencia y el monto del servidor, firmados.
    query = dict(httpx.URL(data["checkout_url"]).params)
    assert data["checkout_url"].startswith("https://checkout.wompi.co/p/?")
    assert (query["reference"], query["amount-in-cents"], query["currency"]) == (
        pago.reference,
        str(PRECIO),
        "COP",
    )
    assert query["signature:integrity"] == integrity_signature(
        pago.reference, PRECIO, "COP", INTEGRITY_SECRET
    )
    assert query["redirect-url"].endswith(f"/pago/{pago.id}")
    assert "prv_test" not in data["checkout_url"]
    assert INTEGRITY_SECRET not in data["checkout_url"]


def test_un_monto_enviado_por_el_cliente_se_ignora(client, db, wompi) -> None:
    """§3.9: el total sale de `pricing.quote`."""
    token, user_id, _ = _cuenta(client, db)
    r = _suscribir(
        client,
        token,
        _mensual(db).id,
        amount_cents=1,
        total_cents=1,
        discount_cents=PRECIO - 1,
        price_cents=1,
        currency="USD",
    )
    assert r.status_code == 202, r.text
    assert r.json()["total_cents"] == PRECIO
    [pago] = _pagos(db, user_id)
    assert (pago.amount_cents, pago.discount_cents, pago.currency) == (PRECIO, 0, "COP")
    assert dict(httpx.URL(r.json()["checkout_url"]).params)["amount-in-cents"] == str(PRECIO)


def test_cuenta_sin_correo_confirmado_no_puede_suscribirse(client, db, wompi) -> None:
    """§5.8."""
    token, user_id, _ = _cuenta(client, db, verificada=False)
    r = _suscribir(client, token, _mensual(db).id)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "email_not_verified"
    assert _suscripciones(db, user_id) == [] and _pagos(db, user_id) == []


def test_cuenta_sin_documentos_aceptados_no_puede_suscribirse(client, db, wompi) -> None:
    token, user_id, _ = _cuenta(client, db)
    db.execute(text("DELETE FROM user_consents WHERE user_id = :id"), {"id": user_id})
    db.commit()
    r = _suscribir(client, token, _mensual(db).id)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "consent_required"
    assert _pagos(db, user_id) == []


def test_cuenta_suspendida_no_puede_suscribirse(client, db, wompi) -> None:
    token, user_id, _ = _cuenta(client, db)
    db.execute(text("UPDATE users SET is_active = false WHERE id = :id"), {"id": user_id})
    db.commit()
    r = _suscribir(client, token, _mensual(db).id)
    assert (r.status_code, r.json()["detail"]["code"]) == (403, "suspended")


def test_sin_sesion_no_se_abre_un_pago(client, db, wompi) -> None:
    r = client.post("/billing/subscriptions", json={"plan_id": str(_mensual(db).id)})
    assert r.status_code == 401


@pytest.mark.parametrize("campo", ["access_type='invited'", "access_type='full'", "role='admin'"])
def test_quien_ya_tiene_acceso_sin_pagar_no_se_suscribe(client, db, wompi, campo: str) -> None:
    """Administrador y acceso manual: no se les cobra (decidido el 2026-10-13)."""
    token, user_id, _ = _cuenta(client, db)
    db.execute(text(f"UPDATE users SET {campo} WHERE id = :id"), {"id": user_id})
    db.commit()
    r = _suscribir(client, token, _mensual(db).id)
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "already_has_access")
    assert _pagos(db, user_id) == []


def test_plan_inexistente_o_desactivado(client, db, wompi) -> None:
    token, _, _ = _cuenta(client, db)
    assert _suscribir(client, token, uuid.uuid4()).status_code == 404
    assert _suscribir(client, token, _plan(db, active=False).id).status_code == 404


def test_sin_pasarela_configurada_no_se_abre_un_pago(client, db) -> None:
    """Sin llaves (el caso de los tests y de produccion hasta que se pongan)."""
    token, user_id, _ = _cuenta(client, db)
    assert client.get("/billing/availability").json()["enabled"] is False
    r = _suscribir(client, token, _mensual(db).id)
    assert (r.status_code, r.json()["detail"]["code"]) == (503, "payments_unavailable")
    assert _pagos(db, user_id) == []


def test_con_pasarela_el_pago_esta_disponible(client, wompi) -> None:
    assert client.get("/billing/availability").json()["enabled"] is True


def test_limite_de_intentos_de_pago(client, db, wompi) -> None:
    token, _, _ = _cuenta(client, db)
    plan_id = _mensual(db).id
    for _ in range(10):
        assert _suscribir(client, token, plan_id).status_code == 202
    assert _suscribir(client, token, plan_id).status_code == 429


# ---------- Cupones al pagar ----------


def test_pago_con_cupon_cobra_el_total_con_descuento(client, db, wompi) -> None:
    token, user_id, _ = _cuenta(client, db)
    cupon = _cupon(db, value=20)
    r = _suscribir(client, token, _mensual(db).id, cupon.code.lower())
    assert r.status_code == 202, r.text
    data = r.json()
    assert (data["subtotal_cents"], data["discount_cents"], data["total_cents"]) == (
        PRECIO,
        2_000_000,
        8_000_000,
    )
    [pago] = _pagos(db, user_id)
    assert (pago.amount_cents, pago.discount_cents, pago.coupon_id) == (8_000_000, 2_000_000, cupon.id)
    # Abrir el pago no redime nada: eso lo hace el pago aprobado.
    db.refresh(cupon)
    assert cupon.redemptions_count == 0


@pytest.mark.parametrize(
    ("campos", "motivo"),
    [
        ({"valid_until": datetime.now(UTC) - timedelta(hours=1)}, "expired"),
        ({"max_redemptions": 3, "redemptions_count": 3}, "exhausted"),
        ({"active": False}, "inactive"),
        ({"valid_from": datetime.now(UTC) + timedelta(days=1)}, "not_started"),
        ({"kind": "fixed_cents", "value": PRECIO, "currency": "COP"}, "covers_total"),
    ],
)
def test_cupon_rechazado_con_motivo_no_abre_el_pago(client, db, wompi, campos, motivo) -> None:
    """§3.9. Al pagar, un cupon que no aplica SI es un error: no se cobra el
    precio completo a quien escribio un codigo."""
    token, user_id, _ = _cuenta(client, db)
    cupon = _cupon(db, **campos)
    r = _suscribir(client, token, _mensual(db).id, cupon.code)
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert (detail["code"], detail["reason"]) == ("coupon_rejected", motivo)
    assert detail["message"]
    assert _suscripciones(db, user_id) == [] and _pagos(db, user_id) == []


def test_cupon_de_otro_plan_rechazado(client, db, wompi) -> None:
    token, user_id, _ = _cuenta(client, db)
    cupon = _cupon(db, planes=[_plan(db)])
    r = _suscribir(client, token, _mensual(db).id, cupon.code)
    assert (r.status_code, r.json()["detail"]["reason"]) == (400, "other_plan")
    assert _pagos(db, user_id) == []


def test_cupon_que_no_existe_rechazado(client, db, wompi) -> None:
    token, _, _ = _cuenta(client, db)
    r = _suscribir(client, token, _mensual(db).id, "NO-EXISTE")
    assert (r.status_code, r.json()["detail"]["reason"]) == (400, "not_found")


def test_cupon_ya_usado_por_la_cuenta_rechazado(client, db, wompi) -> None:
    token, user_id, _ = _cuenta(client, db)
    cupon = _cupon(db)
    db.add(CouponRedemption(coupon_id=cupon.id, user_id=uuid.UUID(user_id)))
    db.commit()
    r = _suscribir(client, token, _mensual(db).id, cupon.code)
    assert (r.status_code, r.json()["detail"]["reason"]) == (400, "already_used")


# ---------- Webhook: pago aprobado ----------


def test_pago_aprobado_activa_la_suscripcion_y_da_acceso(client, db, wompi, outbox) -> None:
    token, user_id, correo = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    outbox.clear()
    antes = datetime.now(UTC)

    tx_id = wompi.transaccion(pago, "APPROVED")
    r = _webhook(client, wompi.evento(tx_id))
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "processed"}

    [suscripcion] = _suscripciones(db, user_id)
    assert suscripcion.status == "active"
    assert antes <= suscripcion.current_period_start <= datetime.now(UTC)
    assert suscripcion.current_period_end == add_interval(suscripcion.current_period_start, "month", 1)
    [pago] = _pagos(db, user_id)
    assert (pago.status, pago.provider_transaction_id) == ("approved", tx_id)
    assert (pago.period_start, pago.period_end) == (
        suscripcion.current_period_start,
        suscripcion.current_period_end,
    )
    assert pago.resolved_at is not None

    assert _tiene_acceso(client, token)
    access = client.get("/auth/me", headers=auth(token)).json()["access"]
    assert (access["granted"], access["reason"]) == (True, "subscription")
    # El acceso sale de la suscripcion: el acceso manual no se toca.
    assert db.scalar(text("SELECT access_type FROM users WHERE id = :id"), {"id": user_id}) == "none"

    # Queda el evento, verificado, procesado y unido a su pago.
    evento = db.scalar(select(PaymentEvent).where(PaymentEvent.payment_id == pago.id))
    assert (evento.signature_verified, evento.event_type, evento.status) == (
        True,
        "transaction.updated",
        "APPROVED",
    )
    assert evento.subscription_id == suscripcion.id and evento.processed_at is not None

    # Bienvenida y recibo.
    assert _asuntos(outbox, correo) == [
        "Tu suscripción a Sebasanálisis está activa",
        "Recibo de tu pago en Sebasanálisis",
    ]
    recibo = outbox[-1].text
    assert "100.000 COP" in recibo and pago.reference in recibo and "Acceso Mensual" in recibo


def test_el_plan_de_dos_meses_compra_dos_meses(client, db, wompi) -> None:
    token, user_id, _ = _cuenta(client, db)
    bimestral = db.scalar(select(Plan).where(Plan.code == "bimestral"))
    _aprobar(client, wompi, _abrir_pago(client, db, token, bimestral))
    [suscripcion] = _suscripciones(db, user_id)
    assert suscripcion.price_cents == 15_000_000
    assert suscripcion.current_period_end == add_interval(suscripcion.current_period_start, "month", 2)


def test_suscripcion_vencida_pierde_el_acceso(client, db, wompi) -> None:
    """§3.9: `current_period_end` en el pasado → acceso revocado."""
    token, user_id, _ = _cuenta(client, db)
    _aprobar(client, wompi, _abrir_pago(client, db, token))
    assert _tiene_acceso(client, token)

    db.execute(
        text("UPDATE subscriptions SET current_period_end = :e WHERE user_id = :u"),
        {"e": datetime.now(UTC) - timedelta(minutes=1), "u": user_id},
    )
    db.commit()
    r = client.get("/sessions", headers=auth(token))
    assert (r.status_code, r.json()["detail"]["code"]) == (403, "expired")


# ---------- Webhook: lo que no debe dar acceso ----------


def test_firma_invalida_se_rechaza_se_guarda_y_no_da_acceso(client, db, wompi, outbox) -> None:
    """§3.9."""
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    outbox.clear()
    # Wompi SI tiene la transaccion aprobada: aun asi, sin firma no se mira.
    tx_id = wompi.transaccion(pago, "APPROVED")
    evento = wompi.evento(tx_id)
    evento["signature"]["checksum"] = "0" * 64
    eventos_antes, consultas_antes = _eventos(db), wompi.consultas

    r = _webhook(client, evento)
    assert r.status_code == 401, r.text

    assert _eventos(db) == eventos_antes + 1
    guardado = db.scalar(
        select(PaymentEvent)
        .where(PaymentEvent.provider_event_id.like("wompi:invalid:%"))
        .order_by(PaymentEvent.created_at.desc())
        .limit(1)
    )
    assert guardado.signature_verified is False
    assert (guardado.payment_id, guardado.subscription_id, guardado.processed_at) == (None, None, None)
    assert guardado.raw_payload["data"]["transaction"]["id"] == tx_id

    assert wompi.consultas == consultas_antes  # ni siquiera se reconsulta
    assert [s.status for s in _suscripciones(db, user_id)] == ["pending"]
    assert [p.status for p in _pagos(db, user_id)] == ["pending"]
    assert not _tiene_acceso(client, token)
    assert outbox == []

    # El mismo cuerpo falso otra vez no crea otra fila.
    assert _webhook(client, evento).status_code == 401
    assert _eventos(db) == eventos_antes + 1


def test_evento_alterado_despues_de_firmado_se_rechaza(client, db, wompi) -> None:
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    evento = wompi.evento(wompi.transaccion(pago, "DECLINED"))
    evento["data"]["transaction"]["status"] = "APPROVED"
    assert _webhook(client, evento).status_code == 401
    assert not _tiene_acceso(client, token)


def test_un_evento_falso_no_ocupa_el_lugar_del_autentico(client, db, wompi) -> None:
    """Quien conozca el checksum de un evento autentico no puede hacerlo pasar
    por "duplicado" mandando antes uno falso."""
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    autentico = wompi.evento(wompi.transaccion(pago, "APPROVED"))
    falso = json.loads(json.dumps(autentico))
    falso["data"]["transaction"]["amount_in_cents"] = 1
    assert _webhook(client, falso).status_code == 401

    assert _webhook(client, autentico).json() == {"status": "processed"}
    assert _tiene_acceso(client, token)


def test_evento_duplicado_otorga_un_solo_periodo(client, db, wompi, outbox) -> None:
    """§3.9: idempotencia por `provider_event_id`."""
    token, user_id, correo = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    outbox.clear()
    evento = wompi.evento(wompi.transaccion(pago, "APPROVED"))

    assert _webhook(client, evento).json() == {"status": "processed"}
    [suscripcion] = _suscripciones(db, user_id)
    vence, eventos = suscripcion.current_period_end, _eventos(db)

    for _ in range(3):
        r = _webhook(client, evento)
        assert (r.status_code, r.json()) == (200, {"status": "duplicate"})

    [suscripcion] = _suscripciones(db, user_id)
    assert suscripcion.current_period_end == vence
    assert _eventos(db) == eventos
    assert len(_pagos(db, user_id)) == 1
    assert len(_asuntos(outbox, correo)) == 2  # una bienvenida y un recibo


def test_dos_eventos_distintos_de_la_misma_transaccion_un_solo_periodo(
    client, db, wompi, outbox
) -> None:
    """La segunda capa: el pago se resuelve una sola vez, llegue lo que llegue."""
    token, user_id, correo = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    outbox.clear()
    tx_id = wompi.transaccion(pago, "APPROVED")

    assert _webhook(client, wompi.evento(tx_id, timestamp=1_760_000_000)).status_code == 200
    vence = _suscripciones(db, user_id)[0].current_period_end
    r = _webhook(client, wompi.evento(tx_id, timestamp=1_760_000_999))
    assert (r.status_code, r.json()) == (200, {"status": "processed"})

    assert _suscripciones(db, user_id)[0].current_period_end == vence
    assert len(_asuntos(outbox, correo)) == 2


def test_transaccion_declinada_no_concede_acceso(client, db, wompi, outbox) -> None:
    """§3.9."""
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    outbox.clear()
    r = _webhook(client, wompi.evento(wompi.transaccion(pago, "DECLINED")))
    assert r.status_code == 200, r.text

    [pago] = _pagos(db, user_id)
    assert (pago.status, pago.failure_reason) == ("declined", "Fondos insuficientes")
    assert (pago.period_start, pago.period_end) == (None, None)
    [suscripcion] = _suscripciones(db, user_id)
    assert (suscripcion.status, suscripcion.current_period_end) == ("pending", None)
    assert not _tiene_acceso(client, token)
    assert outbox == []


@pytest.mark.parametrize("estado", ["DECLINED", "VOIDED", "ERROR", "PENDING"])
def test_webhook_valido_pero_la_reconsulta_dice_otra_cosa(client, db, wompi, estado: str) -> None:
    """§3.9: el evento dice APPROVED con firma valida; Wompi, al reconsultar,
    no. Gana la reconsulta."""
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tx_id = wompi.transaccion(pago, estado)
    r = _webhook(client, wompi.evento(tx_id, status="APPROVED"))
    assert r.status_code == 200, r.text

    [pago] = _pagos(db, user_id)
    assert pago.status == estado.lower()
    assert _suscripciones(db, user_id)[0].status == "pending"
    assert not _tiene_acceso(client, token)


def test_evento_de_una_referencia_desconocida_se_guarda_y_no_mueve_nada(client, db, wompi) -> None:
    """§3.9."""
    token, user_id, _ = _cuenta(client, db)
    _abrir_pago(client, db, token)
    tx_id = wompi.transaccion(None, "APPROVED")
    evento = wompi.evento(tx_id)

    r = _webhook(client, evento)
    assert (r.status_code, r.json()) == (200, {"status": "ignored"})

    guardado = db.scalar(
        select(PaymentEvent).where(
            PaymentEvent.provider_event_id == f"wompi:{evento['signature']['checksum']}"
        )
    )
    assert guardado.signature_verified is True
    assert (guardado.subscription_id, guardado.payment_id) == (None, None)
    assert guardado.processed_at is not None
    assert [p.status for p in _pagos(db, user_id)] == ["pending"]
    assert not _tiene_acceso(client, token)


def test_evento_de_una_transaccion_que_wompi_no_conoce(client, db, wompi) -> None:
    token, _, _ = _cuenta(client, db)
    _abrir_pago(client, db, token)
    r = _webhook(client, wompi.evento("tx-que-no-existe"))
    assert (r.status_code, r.json()) == (200, {"status": "ignored"})
    assert not _tiene_acceso(client, token)


def test_aprobada_por_otro_monto_no_concede_acceso(client, db, wompi) -> None:
    """Una transaccion aprobada por menos de lo que se pidio cobrar."""
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tx_id = wompi.transaccion(pago, "APPROVED", amount_in_cents=100)
    assert _webhook(client, wompi.evento(tx_id)).status_code == 200

    [pago] = _pagos(db, user_id)
    assert pago.status == "error" and "100" in pago.failure_reason
    assert not _tiene_acceso(client, token)


def test_si_wompi_no_responde_el_evento_queda_para_el_reintento(client, db, wompi) -> None:
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    evento = wompi.evento(wompi.transaccion(pago, "APPROVED"))

    wompi.caido = True
    assert _webhook(client, evento).status_code == 502
    assert not _tiene_acceso(client, token)
    guardado = db.scalar(
        select(PaymentEvent).where(
            PaymentEvent.provider_event_id == f"wompi:{evento['signature']['checksum']}"
        )
    )
    assert guardado.signature_verified is True and guardado.processed_at is None

    # Wompi reintenta el mismo evento: ahora si se procesa.
    wompi.caido = False
    assert _webhook(client, evento).json() == {"status": "processed"}
    assert _tiene_acceso(client, token)
    assert len(_pagos(db, user_id)) == 1


@pytest.mark.parametrize("cuerpo", [b"", b"no es json", b"[]", b'{"event": "transaction.updated"}'])
def test_un_cuerpo_que_no_es_un_evento_se_rechaza(client, wompi, cuerpo: bytes) -> None:
    r = client.post("/webhooks/wompi", content=cuerpo, headers={"Content-Type": "application/json"})
    assert r.status_code == 401


def test_sin_pasarela_el_webhook_no_acepta_nada(client, db) -> None:
    r = client.post("/webhooks/wompi", content=b"{}", headers={"Content-Type": "application/json"})
    assert r.status_code == 401


# ---------- Redencion del cupon ----------


def test_un_pago_aprobado_registra_una_sola_redencion(client, db, wompi) -> None:
    token, user_id, _ = _cuenta(client, db)
    cupon = _cupon(db, value=25, max_redemptions=5)
    pago = _abrir_pago(client, db, token, codigo=cupon.code)
    tx_id = wompi.transaccion(pago, "APPROVED")

    evento = wompi.evento(tx_id)
    for _ in range(2):
        assert _webhook(client, evento).status_code == 200
    # Otro evento de la misma transaccion, y la consulta del estado del pago.
    assert _webhook(client, wompi.evento(tx_id, timestamp=1_760_000_555)).status_code == 200
    assert client.get(f"/billing/payments/{pago.id}", headers=auth(token)).status_code == 200

    redenciones = list(
        db.scalars(select(CouponRedemption).where(CouponRedemption.coupon_id == cupon.id))
    )
    assert len(redenciones) == 1
    [suscripcion] = _suscripciones(db, user_id)
    assert (redenciones[0].user_id, redenciones[0].subscription_id) == (
        uuid.UUID(user_id),
        suscripcion.id,
    )
    db.refresh(cupon)
    assert cupon.redemptions_count == 1
    # El precio congelado es el del plan, no el del primer cobro con descuento.
    assert (suscripcion.price_cents, suscripcion.coupon_id) == (PRECIO, cupon.id)
    assert suscripcion.discount_periods_remaining == 0  # cupon `once`

    # La cuenta ya no puede cotizar con ese cupon.
    r = client.post(
        "/billing/quote",
        json={"plan_id": str(_mensual(db).id), "coupon_code": cupon.code},
        headers=auth(token),
    )
    assert r.json()["coupon"]["reason"] == "already_used"


def test_un_pago_declinado_no_redime_el_cupon(client, db, wompi) -> None:
    token, _, _ = _cuenta(client, db)
    cupon = _cupon(db)
    pago = _abrir_pago(client, db, token, codigo=cupon.code)
    _webhook(client, wompi.evento(wompi.transaccion(pago, "DECLINED")))

    db.refresh(cupon)
    assert cupon.redemptions_count == 0
    assert db.scalar(
        select(func.count()).select_from(CouponRedemption).where(CouponRedemption.coupon_id == cupon.id)
    ) == 0
    # Y puede volver a intentarlo con el mismo cupon.
    assert _suscribir(client, token, _mensual(db).id, cupon.code).status_code == 202


@pytest.mark.parametrize(
    ("campos", "quedan"),
    [
        ({"duration": "once"}, 0),
        ({"duration": "repeating", "duration_periods": 3}, 2),
        ({"duration": "forever"}, None),
    ],
)
def test_periodos_con_descuento_que_quedan_tras_el_primer_cobro(
    client, db, wompi, campos, quedan
) -> None:
    """Las renovaciones (entrega 2) descuentan de aqui."""
    token, user_id, _ = _cuenta(client, db)
    cupon = _cupon(db, **campos)
    _aprobar(client, wompi, _abrir_pago(client, db, token, codigo=cupon.code))
    assert _suscripciones(db, user_id)[0].discount_periods_remaining == quedan


# ---------- GET /billing/payments/:id ----------


def test_la_consulta_del_pago_reconsulta_si_el_webhook_no_ha_llegado(
    client, db, wompi, outbox
) -> None:
    """§3.4: las dos vias pasan por la misma funcion."""
    token, user_id, correo = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    outbox.clear()

    r = client.get(f"/billing/payments/{pago.id}", headers=auth(token))
    assert (r.status_code, r.json()["status"]) == (200, "pending")
    assert r.json()["plan_name"] == "Acceso Mensual"

    # El cliente vuelve de Wompi con `?id=`; el webhook todavia no llega.
    tx_id = wompi.transaccion(pago, "APPROVED")
    r = client.get(
        f"/billing/payments/{pago.id}", params={"transaction_id": tx_id}, headers=auth(token)
    )
    data = r.json()
    assert (r.status_code, data["status"]) == (200, "approved")
    assert data["period_end"] is not None and data["amount_cents"] == PRECIO
    assert _tiene_acceso(client, token)
    assert len(_asuntos(outbox, correo)) == 2

    # Despues llega el webhook: no da otro periodo ni otro correo.
    vence = _suscripciones(db, user_id)[0].current_period_end
    assert _webhook(client, wompi.evento(tx_id)).status_code == 200
    assert _suscripciones(db, user_id)[0].current_period_end == vence
    assert len(_asuntos(outbox, correo)) == 2


def test_el_id_de_una_transaccion_ajena_no_resuelve_el_pago(client, db, wompi) -> None:
    """`transaction_id` viene del navegador: solo vale si Wompi dice que esa
    transaccion es de la referencia de este pago."""
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    otro_token, otro_id, _ = _cuenta(client, db)
    pago_ajeno = _abrir_pago(client, db, otro_token)
    tx_ajena = wompi.transaccion(pago_ajeno, "APPROVED")

    r = client.get(
        f"/billing/payments/{pago.id}", params={"transaction_id": tx_ajena}, headers=auth(token)
    )
    assert r.json()["status"] == "pending"
    assert not _tiene_acceso(client, token)
    # Tampoco le activo nada al dueno de esa transaccion por una consulta ajena.
    assert [p.status for p in _pagos(db, otro_id)] == ["pending"]


def test_un_pago_ajeno_no_se_ve(client, db, wompi) -> None:
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    otro_token, _, _ = _cuenta(client, db)
    assert client.get(f"/billing/payments/{pago.id}", headers=auth(otro_token)).status_code == 404
    assert client.get(f"/billing/payments/{uuid.uuid4()}", headers=auth(token)).status_code == 404
    assert client.get(f"/billing/payments/{pago.id}").status_code == 401


def test_si_wompi_no_responde_la_consulta_dice_pendiente(client, db, wompi) -> None:
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tx_id = wompi.transaccion(pago, "APPROVED")
    wompi.caido = True
    r = client.get(
        f"/billing/payments/{pago.id}", params={"transaction_id": tx_id}, headers=auth(token)
    )
    assert (r.status_code, r.json()["status"]) == (200, "pending")


def test_un_pago_resuelto_no_se_reconsulta(client, db, wompi) -> None:
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    _aprobar(client, wompi, pago)
    consultas = wompi.consultas
    assert client.get(f"/billing/payments/{pago.id}", headers=auth(token)).json()["status"] == "approved"
    assert wompi.consultas == consultas


# ---------- El periodo siguiente ----------


def test_pagar_antes_del_vencimiento_extiende_desde_el_vencimiento(client, db, wompi, outbox) -> None:
    """Decidido el 2026-10-13: no se pierden los dias que quedaban."""
    token, user_id, correo = _cuenta(client, db)
    _aprobar(client, wompi, _abrir_pago(client, db, token))
    [suscripcion] = _suscripciones(db, user_id)
    inicio, vence = suscripcion.current_period_start, suscripcion.current_period_end
    outbox.clear()

    # El precio del plan sube: la suscripcion vigente paga su precio congelado (§3.7).
    db.execute(text("UPDATE plans SET price_cents = 12000000 WHERE code = 'mensual'"))
    db.commit()
    try:
        segundo = _abrir_pago(client, db, token)
        assert (segundo.kind, segundo.amount_cents) == ("renewal", PRECIO)
        _aprobar(client, wompi, segundo, timestamp=1_760_000_111)
    finally:
        db.execute(text("UPDATE plans SET price_cents = 10000000 WHERE code = 'mensual'"))
        db.commit()

    [suscripcion] = _suscripciones(db, user_id)
    assert suscripcion.status == "active"
    assert suscripcion.current_period_start == inicio
    assert suscripcion.current_period_end == add_interval(vence, "month", 1)
    segundo = _pagos(db, user_id)[1]
    assert (segundo.period_start, segundo.period_end) == (vence, add_interval(vence, "month", 1))
    # Solo el recibo: la bienvenida va una vez.
    assert _asuntos(outbox, correo) == ["Recibo de tu pago en Sebasanálisis"]


def test_pagar_despues_del_vencimiento_cuenta_desde_el_pago(client, db, wompi) -> None:
    token, user_id, _ = _cuenta(client, db)
    _aprobar(client, wompi, _abrir_pago(client, db, token))
    vencio = datetime.now(UTC) - timedelta(days=10)
    db.execute(
        text("UPDATE subscriptions SET current_period_end = :e WHERE user_id = :u"),
        {"e": vencio, "u": user_id},
    )
    db.commit()
    assert not _tiene_acceso(client, token)

    antes = datetime.now(UTC)
    _aprobar(client, wompi, _abrir_pago(client, db, token), timestamp=1_760_000_222)
    # La que vencio queda como historia; la nueva es la que cuenta.
    [suscripcion] = [s for s in _suscripciones(db, user_id) if s.status != "expired"]
    assert suscripcion.current_period_start >= antes
    assert suscripcion.current_period_end == add_interval(suscripcion.current_period_start, "month", 1)
    assert _tiene_acceso(client, token)


def test_con_el_periodo_vencido_se_puede_volver_con_otro_plan(client, db, wompi) -> None:
    """Volver despues de vencido es un alta nueva: otro plan, y al precio de hoy."""
    token, user_id, _ = _cuenta(client, db)
    _aprobar(client, wompi, _abrir_pago(client, db, token))
    db.execute(
        text("UPDATE subscriptions SET current_period_end = :e WHERE user_id = :u"),
        {"e": datetime.now(UTC) - timedelta(days=2), "u": user_id},
    )
    db.commit()
    bimestral = db.scalar(select(Plan).where(Plan.code == "bimestral"))

    pago = _abrir_pago(client, db, token, bimestral)
    assert (pago.kind, pago.amount_cents) == ("initial", 15_000_000)
    # La que vencio queda como historia, vencida; la nueva espera el pago.
    assert sorted((s.status, s.plan_id) for s in _suscripciones(db, user_id)) == sorted(
        [("expired", _mensual(db).id), ("pending", bimestral.id)]
    )

    _aprobar(client, wompi, pago, timestamp=1_760_000_333)
    [suscripcion] = [s for s in _suscripciones(db, user_id) if s.status != "expired"]
    assert (suscripcion.status, suscripcion.plan_id, suscripcion.price_cents) == (
        "active",
        bimestral.id,
        15_000_000,
    )
    assert suscripcion.current_period_end == add_interval(suscripcion.current_period_start, "month", 2)
    assert _tiene_acceso(client, token)


def test_con_suscripcion_pagada_no_se_paga_otro_plan_ni_se_usa_cupon(client, db, wompi) -> None:
    token, user_id, _ = _cuenta(client, db)
    _aprobar(client, wompi, _abrir_pago(client, db, token))
    bimestral = db.scalar(select(Plan).where(Plan.code == "bimestral"))

    r = _suscribir(client, token, bimestral.id)
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "other_plan")
    r = _suscribir(client, token, _mensual(db).id, _cupon(db).code)
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "coupon_only_on_first_payment")
    assert len(_pagos(db, user_id)) == 1


def test_un_pago_que_no_se_completo_se_puede_cambiar_por_otro_plan(client, db, wompi) -> None:
    """Abrio el pago del mensual, se devolvio y eligio el de dos meses: una
    sola suscripcion pendiente. Lo que se compra lo dice el pago aprobado."""
    token, user_id, _ = _cuenta(client, db)
    bimestral = db.scalar(select(Plan).where(Plan.code == "bimestral"))
    primero = _abrir_pago(client, db, token)
    _abrir_pago(client, db, token, bimestral)

    [suscripcion] = _suscripciones(db, user_id)
    assert (suscripcion.status, suscripcion.plan_id) == ("pending", bimestral.id)

    # Termina pagando el primero, que seguia abierto en otra pestana.
    _aprobar(client, wompi, primero)
    [suscripcion] = _suscripciones(db, user_id)
    assert (suscripcion.plan_id, suscripcion.price_cents) == (_mensual(db).id, PRECIO)
    assert suscripcion.current_period_end == add_interval(suscripcion.current_period_start, "month", 1)


def test_la_base_no_admite_dos_suscripciones_vivas_por_cuenta(client, db, wompi) -> None:
    """§3.4: la restriccion vive en la base, no solo en el codigo."""
    token, user_id, _ = _cuenta(client, db)
    _abrir_pago(client, db, token)
    plan = _mensual(db)
    for estado in ("pending", "active", "past_due"):
        db.add(
            Subscription(
                user_id=uuid.UUID(user_id),
                plan_id=plan.id,
                provider="wompi",
                status=estado,
                price_cents=PRECIO,
                currency="COP",
            )
        )
        with pytest.raises(IntegrityError, match="uq_subscriptions_one_live_per_user"):
            db.commit()
        db.rollback()
    # Una vencida o cancelada no estorba.
    db.add(
        Subscription(
            user_id=uuid.UUID(user_id),
            plan_id=plan.id,
            provider="wompi",
            status="expired",
            price_cents=PRECIO,
            currency="COP",
        )
    )
    db.commit()


# ---------- GET /billing/subscription ----------


def test_la_suscripcion_de_la_cuenta(client, db, wompi) -> None:
    token, _, _ = _cuenta(client, db)
    assert client.get("/billing/subscription").status_code == 401
    assert client.get("/billing/subscription", headers=auth(token)).json() is None

    pago = _abrir_pago(client, db, token)
    # Una que nunca se pago no cuenta.
    assert client.get("/billing/subscription", headers=auth(token)).json() is None

    _aprobar(client, wompi, pago)
    data = client.get("/billing/subscription", headers=auth(token)).json()
    assert (data["status"], data["renewal_mode"], data["price_cents"], data["currency"]) == (
        "active",
        "manual",
        PRECIO,
        "COP",
    )
    assert data["plan"]["code"] == "mensual"
    assert data["current_period_end"] is not None and data["cancel_at_period_end"] is False
    assert data["in_force"] is True


# ---------- Eliminar la cuenta ----------


def test_eliminar_la_cuenta_conserva_el_pago_sin_usuario(client, db, wompi) -> None:
    """Decidido el 2026-10-13. El flujo completo (cancelar la renovacion antes
    de borrar) es de la entrega 3; aqui se fija lo que hacen las llaves."""
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    _aprobar(client, wompi, pago)
    pago_id = pago.id

    r = client.request(
        "DELETE", "/auth/me", json={"password": "clave-segura-123"}, headers=auth(token)
    )
    assert r.status_code == 204, r.text

    db.expire_all()
    assert _suscripciones(db, user_id) == []
    conservado = db.get(Payment, pago_id)
    assert (conservado.user_id, conservado.subscription_id) == (None, None)
    assert (conservado.status, conservado.amount_cents, conservado.currency) == ("approved", PRECIO, "COP")
    evento = db.scalar(select(PaymentEvent).where(PaymentEvent.payment_id == pago_id))
    assert evento is not None and evento.subscription_id is None


# ---------- Pasarela simulada ----------


def test_la_pasarela_simulada_no_existe_con_wompi(client, db, wompi) -> None:
    r = client.get(
        "/dev/fake-checkout",
        params={
            "reference": "x",
            "amount_cents": 1,
            "currency": "COP",
            "redirect_url": "http://localhost:3000/pago/1",
        },
    )
    assert r.status_code == 404
    assert "/dev/fake-checkout" not in client.get("/openapi.json").json()["paths"]


def test_flujo_completo_con_la_pasarela_simulada(client, db) -> None:
    from app.main import app

    fake = FakePaymentProvider(api_base_url="http://testserver")
    anterior = app.dependency_overrides.get(get_payment_provider)
    app.dependency_overrides[get_payment_provider] = lambda: fake
    try:
        token, user_id, _ = _cuenta(client, db)
        r = _suscribir(client, token, _mensual(db).id)
        assert r.status_code == 202, r.text
        url = httpx.URL(r.json()["checkout_url"])
        assert url.path == "/dev/fake-checkout"
        params = dict(url.params)

        pagina = client.get(url.path, params=params)
        assert pagina.status_code == 200 and "Pasarela simulada" in pagina.text

        # Solo devuelve al frontend de esta instalacion.
        r = client.post(
            url.path,
            data={**params, "redirect_url": "https://otro-sitio.com/x", "outcome": "approved"},
            follow_redirects=False,
        )
        assert r.status_code == 400

        r = client.post(url.path, data={**params, "outcome": "approved"}, follow_redirects=False)
        assert r.status_code == 303
        regreso = httpx.URL(r.headers["location"])
        assert regreso.path == f"/pago/{_pagos(db, user_id)[0].id}"

        pago = client.get(
            f"/billing/payments/{_pagos(db, user_id)[0].id}",
            params={"transaction_id": regreso.params["id"]},
            headers=auth(token),
        )
        assert pago.json()["status"] == "approved"
        assert _tiene_acceso(client, token)

        # Su webhook exige su propia marca: sin ella, se rechaza.
        cuerpo = json.dumps({"id": "evt-1", "transaction_id": regreso.params["id"]})
        assert client.post("/webhooks/wompi", content=cuerpo).status_code == 401
        r = client.post(
            "/webhooks/wompi", content=cuerpo, headers={FAKE_SIGNATURE_HEADER: FAKE_SIGNATURE}
        )
        assert r.status_code == 200
    finally:
        app.dependency_overrides[get_payment_provider] = anterior


def test_las_transacciones_de_wompi_no_se_mezclan_con_las_de_otro_test() -> None:
    """El doble de Wompi es por test: no hay estado compartido."""
    assert Wompi().transactions == {}


def test_coupon_no_se_reutiliza_en_dos_cuentas_mas_alla_del_tope(client, db, wompi) -> None:
    """El tope de usos se revisa al abrir el pago."""
    cupon = _cupon(db, max_redemptions=1)
    token_a, _, _ = _cuenta(client, db)
    _aprobar(client, wompi, _abrir_pago(client, db, token_a, codigo=cupon.code))
    token_b, _, _ = _cuenta(client, db)
    r = _suscribir(client, token_b, _mensual(db).id, cupon.code)
    assert (r.status_code, r.json()["detail"]["reason"]) == (400, "exhausted")
    assert db.get(Coupon, cupon.id).redemptions_count == 1


# ---------- Historial de pagos de la cuenta (GET /billing/payments) ----------


def test_historial_de_pagos_de_la_cuenta(client, db, wompi) -> None:
    token, user_id, _ = _cuenta(client, db)
    assert client.get("/billing/payments").status_code == 401
    assert client.get("/billing/payments", headers=auth(token)).json() == {
        "items": [],
        "total": 0,
        "limit": 20,
        "offset": 0,
    }

    rechazado = _abrir_pago(client, db, token)
    _webhook(client, wompi.evento(wompi.transaccion(rechazado, "DECLINED")))
    aprobado = _abrir_pago(client, db, token)
    _aprobar(client, wompi, aprobado, timestamp=1_760_000_444)
    # Uno que se abrio y no se completo: no es historia.
    _abrir_pago(client, db, token)

    data = client.get("/billing/payments", headers=auth(token)).json()
    assert data["total"] == 2
    assert [(p["id"], p["status"]) for p in data["items"]] == [
        (str(aprobado.id), "approved"),
        (str(rechazado.id), "declined"),
    ]
    primero = data["items"][0]
    assert (primero["plan_name"], primero["amount_cents"], primero["currency"]) == (
        "Acceso Mensual",
        PRECIO,
        "COP",
    )
    assert primero["period_end"] is not None
    # Al cliente no le llega la referencia ni lo que dijo el proveedor.
    assert "reference" not in primero and "failure_reason" not in data["items"][1]

    # Paginado, y solo lo propio.
    pagina = client.get("/billing/payments", params={"limit": 1, "offset": 1}, headers=auth(token)).json()
    assert (pagina["total"], [p["id"] for p in pagina["items"]]) == (2, [str(rechazado.id)])
    otro_token, _, _ = _cuenta(client, db)
    assert client.get("/billing/payments", headers=auth(otro_token)).json()["total"] == 0


# ---------- Admin: suscripcion y pagos en el detalle, y filtro de la lista ----------


def test_admin_ve_la_suscripcion_y_los_pagos_de_una_cuenta(client, db, wompi, admin_token) -> None:
    token, user_id, _ = _cuenta(client, db)
    detalle = client.get(f"/admin/users/{user_id}", headers=auth(admin_token)).json()
    assert (detalle["subscription"], detalle["payments"]) == (None, [])

    rechazado = _abrir_pago(client, db, token)
    _webhook(client, wompi.evento(wompi.transaccion(rechazado, "DECLINED")))
    aprobado = _abrir_pago(client, db, token)
    tx_id = _aprobar(client, wompi, aprobado, timestamp=1_760_000_444)
    sin_completar = _abrir_pago(client, db, token)

    detalle = client.get(f"/admin/users/{user_id}", headers=auth(admin_token)).json()
    suscripcion = detalle["subscription"]
    assert (suscripcion["status"], suscripcion["in_force"], suscripcion["renewal_mode"]) == (
        "active",
        True,
        "manual",
    )
    assert (suscripcion["plan"]["code"], suscripcion["price_cents"]) == ("mensual", PRECIO)
    assert detalle["user"]["access"]["reason"] == "subscription"

    # Todos los intentos, tambien el que no se completo, lo mas reciente primero.
    assert [(p["id"], p["status"]) for p in detalle["payments"]] == [
        (str(sin_completar.id), "pending"),
        (str(aprobado.id), "approved"),
        (str(rechazado.id), "declined"),
    ]
    visto = detalle["payments"][1]
    assert (visto["reference"], visto["provider_transaction_id"]) == (aprobado.reference, tx_id)
    assert detalle["payments"][2]["failure_reason"] == "Fondos insuficientes"

    # Solo un administrador.
    assert client.get(f"/admin/users/{user_id}", headers=auth(token)).status_code == 403


def test_admin_filtra_las_cuentas_por_suscripcion(client, db, wompi, admin_token) -> None:
    def cuenta_y_correo() -> tuple[str, str, str]:
        return _cuenta(client, db)

    def filtrar(valor: str, correo: str) -> list[str]:
        r = client.get(
            "/admin/users",
            params={"subscription": valor, "query": correo},
            headers=auth(admin_token),
        )
        assert r.status_code == 200, r.text
        return [u["email"] for u in r.json()["items"]]

    # Vigente.
    t_vigente, _, vigente = cuenta_y_correo()
    _aprobar(client, wompi, _abrir_pago(client, db, t_vigente), timestamp=1_760_001_001)
    # Vencida: pago y el periodo ya paso.
    t_vencida, id_vencida, vencida = cuenta_y_correo()
    _aprobar(client, wompi, _abrir_pago(client, db, t_vencida), timestamp=1_760_001_002)
    db.execute(
        text("UPDATE subscriptions SET current_period_end = :e WHERE user_id = :u"),
        {"e": datetime.now(UTC) - timedelta(days=1), "u": id_vencida},
    )
    db.commit()
    # Pago sin completar.
    t_pendiente, _, pendiente = cuenta_y_correo()
    _abrir_pago(client, db, t_pendiente)
    # Nunca abrio un pago.
    _, _, ninguna = cuenta_y_correo()

    esperado = {"in_force": vigente, "lapsed": vencida, "pending": pendiente, "none": ninguna}
    for valor, correo in esperado.items():
        assert filtrar(valor, correo) == [correo], valor
        for otro in esperado.values():
            if otro != correo:
                assert filtrar(valor, otro) == [], (valor, otro)

    # La fila trae la decision de acceso de siempre: el filtro no decide nada.
    r = client.get(
        "/admin/users", params={"subscription": "in_force", "query": vigente}, headers=auth(admin_token)
    )
    assert r.json()["items"][0]["access"]["reason"] == "subscription"
    r = client.get("/admin/users", params={"subscription": "otra-cosa"}, headers=auth(admin_token))
    assert r.status_code == 422
