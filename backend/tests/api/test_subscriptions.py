"""Alta con pago manual, webhook y reconsulta (§3.4 y §3.9 de la Fase 4).

La pasarela es Tipster Page: su proveedor de verdad (`TipsterPageProvider`)
sobre un transporte HTTP simulado (`tipster_sandbox.py`). Ningun test sale a la
red, y aun asi pasan por la firma de la orden, la del aviso, la reconsulta y la
traduccion de estados. Lo nuevo del paso 5.3 de la Fase 5 (el monto crudo, el
`error` que pasa a `paid`, la pagina de un solo uso, los datos del comprador)
esta en `test_tipster_page.py`.
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
from tests.api.conftest import auth, register_raw
from tests.api.pasarela_simulada import Aviso
from tests.api.test_billing import _cupon, _mensual, _plan
from tests.api.tipster_sandbox import SECRETO, TipsterSandbox, firma_de_aviso

PRECIO = 3_200  # 32 EUR en centavos
PRECIO_BIMESTRAL = 4_600  # 46 EUR


# ---------- Ayudas ----------


def _datos_de_facturacion(db, user_id) -> None:
    """Los datos de facturacion de un cliente inventado (§3.17, "Paso 5.4"):
    sin ellos no se abre un pago."""
    db.execute(
        text(
            "INSERT INTO billing_profiles (id, user_id, first_names, last_names, id_type,"
            " id_number, country_code, state_code, city_code, address)"
            " VALUES (gen_random_uuid(), :id, 'Cliente', 'De Prueba', '13', '1234567890',"
            " 'Co', '11', '11001', 'Calle 1 # 2-3')"
        ),
        {"id": user_id},
    )


def _cuenta(
    client: TestClient, db, *, verificada: bool = True, facturacion: bool = True
) -> tuple[str, str, str]:
    """Una cuenta como la de un cliente nuevo: consentimientos aceptados, sin
    acceso y, salvo que se pida lo contrario, con sus datos de facturacion.
    Devuelve (token, id, correo)."""
    email = f"pago-{uuid.uuid4().hex[:12]}@ejemplo.com"
    registro = register_raw(client, email)
    user_id = registro["user"]["id"]
    if verificada:
        db.execute(text("UPDATE users SET email_verified = true WHERE id = :id"), {"id": user_id})
    if facturacion:
        _datos_de_facturacion(db, user_id)
    db.commit()
    return registro["access_token"], user_id, email


def _suscribir(
    client: TestClient,
    token: str,
    plan_id,
    codigo: str | None = None,
    *,
    metodo: str | None = "cardtpv",
    pais: str | None = None,
    comprador: dict | None = None,
    **extra,
):
    body = {"plan_id": str(plan_id), **extra}
    if metodo is not None:
        body["payment_method"] = metodo
    if pais is not None:
        body["country"] = pais
    if comprador is not None:
        body["buyer"] = comprador
    if codigo is not None:
        body["coupon_code"] = codigo
    return client.post("/billing/subscriptions", json=body, headers=auth(token))


def _abrir_pago(client: TestClient, db, token: str, plan: Plan | None = None, codigo=None) -> Payment:
    r = _suscribir(client, token, (plan or _mensual(db)).id, codigo)
    assert r.status_code == 202, r.text
    return db.get(Payment, uuid.UUID(r.json()["payment_id"]))


def _webhook(client: TestClient, aviso: bytes | Aviso):
    if isinstance(aviso, Aviso):
        body, headers = aviso.body, aviso.headers
    else:
        body, headers = aviso, {}
    return client.post(
        "/webhooks/payments",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )


def _aprobar(client: TestClient, pasarela, payment: Payment) -> None:
    """El cliente paga y llega el aviso de la pasarela (Tipster Page o la simulada)."""
    r = _webhook(client, pasarela.aprobar(payment))
    assert r.status_code == 200, r.text


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


def test_abrir_el_pago_deja_todo_pendiente_y_no_da_acceso(client, db, tipster: TipsterSandbox) -> None:
    token, user_id, _ = _cuenta(client, db)
    r = _suscribir(client, token, _mensual(db).id)
    assert r.status_code == 202, r.text
    data = r.json()
    assert (data["subtotal_cents"], data["discount_cents"], data["total_cents"]) == (PRECIO, 0, PRECIO)
    assert data["currency"] == "EUR"

    [suscripcion] = _suscripciones(db, user_id)
    assert (suscripcion.status, suscripcion.renewal_mode, suscripcion.provider) == (
        "pending",
        "manual",
        "tipsterpage",
    )
    assert (suscripcion.price_cents, suscripcion.currency) == (PRECIO, "EUR")
    assert suscripcion.current_period_end is None
    # No se tokeniza nada en el pago manual.
    assert (suscripcion.payment_source_id, suscripcion.card_brand, suscripcion.card_last4) == (
        None,
        None,
        None,
    )
    [pago] = _pagos(db, user_id)
    assert (pago.status, pago.kind, pago.amount_cents, pago.currency) == ("pending", "initial", PRECIO, "EUR")
    assert str(pago.id) == data["payment_id"]
    # La orden ya existe en la pasarela, con nuestra referencia como id.
    assert pago.provider_transaction_id == pago.reference
    assert not _tiene_acceso(client, token)

    # La orden lleva la referencia, el plan y el monto del servidor, en euros.
    [pedido] = tipster.pedidos
    assert (pedido["order_id"], pedido["product_id"], pedido["amount"]) == (
        pago.reference,
        "mensual",
        "32.00",
    )
    assert (pedido["product_name"], pedido["product_description"]) == (
        "Acceso Mensual",
        "Sebasanalisis: acceso por 1 mes",
    )
    assert pedido["payment_method"] == "cardtpv" and "country" not in pedido
    assert pedido["url_ok"].endswith(f"/pago/{pago.id}") and pedido["url_ko"].endswith(f"/pago/{pago.id}")
    assert pedido["notification_url"].endswith("/webhooks/payments")

    # El navegador recibe un enlace de un solo uso a la API, no la pagina.
    url = httpx.URL(data["checkout_url"])
    assert url.path.startswith("/billing/checkout/")
    assert SECRETO not in data["checkout_url"]


def test_un_monto_enviado_por_el_cliente_se_ignora(client, db, tipster) -> None:
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
        amount="0.01",
    )
    assert r.status_code == 202, r.text
    assert r.json()["total_cents"] == PRECIO
    [pago] = _pagos(db, user_id)
    assert (pago.amount_cents, pago.discount_cents, pago.currency) == (PRECIO, 0, "EUR")
    assert tipster.pedidos[0]["amount"] == "32.00"


def test_cuenta_sin_correo_confirmado_no_puede_suscribirse(client, db, tipster) -> None:
    """§5.8."""
    token, user_id, _ = _cuenta(client, db, verificada=False)
    r = _suscribir(client, token, _mensual(db).id)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "email_not_verified"
    assert _suscripciones(db, user_id) == [] and _pagos(db, user_id) == []
    assert tipster.pedidos == []


def test_cuenta_sin_documentos_aceptados_no_puede_suscribirse(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db)
    db.execute(text("DELETE FROM user_consents WHERE user_id = :id"), {"id": user_id})
    db.commit()
    r = _suscribir(client, token, _mensual(db).id)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "consent_required"
    assert _pagos(db, user_id) == []


def test_cuenta_suspendida_no_puede_suscribirse(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db)
    db.execute(text("UPDATE users SET is_active = false WHERE id = :id"), {"id": user_id})
    db.commit()
    r = _suscribir(client, token, _mensual(db).id)
    assert (r.status_code, r.json()["detail"]["code"]) == (403, "suspended")


def test_sin_sesion_no_se_abre_un_pago(client, db, tipster) -> None:
    r = client.post("/billing/subscriptions", json={"plan_id": str(_mensual(db).id)})
    assert r.status_code == 401


@pytest.mark.parametrize("campo", ["access_type='invited'", "access_type='full'", "role='admin'"])
def test_quien_ya_tiene_acceso_sin_pagar_no_se_suscribe(client, db, tipster, campo: str) -> None:
    """Administrador y acceso manual: no se les cobra (decidido el 2026-10-13)."""
    token, user_id, _ = _cuenta(client, db)
    db.execute(text(f"UPDATE users SET {campo} WHERE id = :id"), {"id": user_id})
    db.commit()
    r = _suscribir(client, token, _mensual(db).id)
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "already_has_access")
    assert _pagos(db, user_id) == []


def test_plan_inexistente_o_desactivado(client, db, tipster) -> None:
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


def test_con_tipster_page_el_pago_esta_disponible_sin_renovacion_automatica(client, tipster) -> None:
    """Tipster Page no tiene cobros recurrentes: no se ofrece guardar un medio."""
    assert client.get("/billing/availability").json() == {"enabled": True, "tokenizer": None}


def test_limite_de_intentos_de_pago(client, db, tipster) -> None:
    token, _, _ = _cuenta(client, db)
    plan_id = _mensual(db).id
    for _ in range(10):
        assert _suscribir(client, token, plan_id).status_code == 202
    assert _suscribir(client, token, plan_id).status_code == 429


# ---------- Cupones al pagar ----------


def test_pago_con_cupon_cobra_el_total_con_descuento(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db)
    cupon = _cupon(db, value=20)
    r = _suscribir(client, token, _mensual(db).id, cupon.code.lower())
    assert r.status_code == 202, r.text
    data = r.json()
    assert (data["subtotal_cents"], data["discount_cents"], data["total_cents"]) == (PRECIO, 640, 2_560)
    [pago] = _pagos(db, user_id)
    assert (pago.amount_cents, pago.discount_cents, pago.coupon_id) == (2_560, 640, cupon.id)
    assert tipster.pedidos[0]["amount"] == "25.60"
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
        ({"kind": "fixed_cents", "value": PRECIO, "currency": "EUR"}, "covers_total"),
        ({"kind": "fixed_cents", "value": 500, "currency": "COP"}, "currency_mismatch"),
    ],
)
def test_cupon_rechazado_con_motivo_no_abre_el_pago(client, db, tipster, campos, motivo) -> None:
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
    assert tipster.pedidos == []


def test_cupon_de_otro_plan_rechazado(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db)
    cupon = _cupon(db, planes=[_plan(db)])
    r = _suscribir(client, token, _mensual(db).id, cupon.code)
    assert (r.status_code, r.json()["detail"]["reason"]) == (400, "other_plan")
    assert _pagos(db, user_id) == []


def test_cupon_que_no_existe_rechazado(client, db, tipster) -> None:
    token, _, _ = _cuenta(client, db)
    r = _suscribir(client, token, _mensual(db).id, "NO-EXISTE")
    assert (r.status_code, r.json()["detail"]["reason"]) == (400, "not_found")


def test_cupon_ya_usado_por_la_cuenta_rechazado(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db)
    cupon = _cupon(db)
    db.add(CouponRedemption(coupon_id=cupon.id, user_id=uuid.UUID(user_id)))
    db.commit()
    r = _suscribir(client, token, _mensual(db).id, cupon.code)
    assert (r.status_code, r.json()["detail"]["reason"]) == (400, "already_used")


# ---------- Webhook: pago aprobado ----------


def test_pago_aprobado_activa_la_suscripcion_y_da_acceso(client, db, tipster, outbox) -> None:
    token, user_id, correo = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    outbox.clear()
    antes = datetime.now(UTC)

    tipster.pagar(pago, "paid")
    r = _webhook(client, tipster.aviso(pago, "ok"))
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "processed"}

    [suscripcion] = _suscripciones(db, user_id)
    assert suscripcion.status == "active"
    assert antes <= suscripcion.current_period_start <= datetime.now(UTC)
    assert suscripcion.current_period_end == add_interval(suscripcion.current_period_start, "month", 1)
    [pago] = _pagos(db, user_id)
    assert (pago.status, pago.provider_transaction_id) == ("approved", pago.reference)
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

    # Queda el evento, verificado, procesado, con su pasarela y unido a su pago.
    evento = db.scalar(select(PaymentEvent).where(PaymentEvent.payment_id == pago.id))
    assert (evento.signature_verified, evento.event_type, evento.status) == (
        True,
        "order.notification",
        "ok",
    )
    assert (evento.provider, evento.provider_event_id) == (
        "tipsterpage",
        f"tipsterpage:{pago.reference}:ok",
    )
    assert evento.subscription_id == suscripcion.id and evento.processed_at is not None

    # Bienvenida y recibo.
    assert _asuntos(outbox, correo) == [
        "Tu suscripción a Sebasanálisis está activa",
        "Recibo de tu pago en Sebasanálisis",
    ]
    recibo = outbox[-1].text
    assert "32 EUR" in recibo and pago.reference in recibo and "Acceso Mensual" in recibo


def test_el_plan_de_dos_meses_compra_dos_meses(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db)
    bimestral = db.scalar(select(Plan).where(Plan.code == "bimestral"))
    _aprobar(client, tipster, _abrir_pago(client, db, token, bimestral))
    [suscripcion] = _suscripciones(db, user_id)
    assert suscripcion.price_cents == PRECIO_BIMESTRAL
    assert suscripcion.current_period_end == add_interval(suscripcion.current_period_start, "month", 2)
    assert tipster.pedidos[0]["product_description"] == "Sebasanalisis: acceso por 2 meses"


def test_suscripcion_vencida_pierde_el_acceso(client, db, tipster) -> None:
    """§3.9: `current_period_end` en el pasado → acceso revocado."""
    token, user_id, _ = _cuenta(client, db)
    _aprobar(client, tipster, _abrir_pago(client, db, token))
    assert _tiene_acceso(client, token)

    db.execute(
        text("UPDATE subscriptions SET current_period_end = :e WHERE user_id = :u"),
        {"e": datetime.now(UTC) - timedelta(minutes=1), "u": user_id},
    )
    db.commit()
    r = client.get("/sessions", headers=auth(token))
    assert (r.status_code, r.json()["detail"]["code"]) == (403, "expired")


# ---------- Webhook: lo que no debe dar acceso ----------


def test_firma_invalida_se_rechaza_se_guarda_y_no_da_acceso(client, db, tipster, outbox) -> None:
    """§3.9."""
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    outbox.clear()
    # La pasarela SI tiene la orden pagada: aun asi, sin firma no se mira.
    tipster.pagar(pago, "paid")
    aviso = tipster.aviso(pago, "ok", firma="0" * 64)
    eventos_antes, consultas_antes = _eventos(db), tipster.consultas

    r = _webhook(client, aviso)
    assert r.status_code == 401, r.text

    assert _eventos(db) == eventos_antes + 1
    guardado = db.scalar(
        select(PaymentEvent)
        .where(PaymentEvent.provider_event_id.like("tipsterpage:invalid:%"))
        .order_by(PaymentEvent.created_at.desc())
        .limit(1)
    )
    assert (guardado.signature_verified, guardado.provider) == (False, "tipsterpage")
    assert (guardado.payment_id, guardado.subscription_id, guardado.processed_at) == (None, None, None)
    assert guardado.raw_payload["order_id"] == pago.reference

    assert tipster.consultas == consultas_antes  # ni siquiera se reconsulta
    assert [s.status for s in _suscripciones(db, user_id)] == ["pending"]
    assert [p.status for p in _pagos(db, user_id)] == ["pending"]
    assert not _tiene_acceso(client, token)
    assert outbox == []

    # El mismo cuerpo falso otra vez no crea otra fila.
    assert _webhook(client, aviso).status_code == 401
    assert _eventos(db) == eventos_antes + 1


def test_firma_con_otro_secreto_se_rechaza(client, db, tipster) -> None:
    import hashlib
    import hmac

    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tipster.pagar(pago, "paid")
    otra = hmac.new(b"otro-secreto", f"ok{pago.reference}32".encode(), hashlib.sha256).hexdigest()
    assert _webhook(client, tipster.aviso(pago, "ok", firma=otra)).status_code == 401
    assert not _tiene_acceso(client, token)


def test_aviso_alterado_despues_de_firmado_se_rechaza(client, db, tipster) -> None:
    """Firmado como `ko`, enviado como `ok`."""
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tipster.pagar(pago, "paid")
    firma_ko = firma_de_aviso("ko", pago.reference, "32")
    assert _webhook(client, tipster.aviso(pago, "ok", firma=firma_ko)).status_code == 401
    assert not _tiene_acceso(client, token)


def test_un_aviso_falso_no_ocupa_el_lugar_del_autentico(client, db, tipster) -> None:
    """Quien conozca la orden no puede hacer pasar por "duplicado" el aviso
    autentico mandando antes uno falso con el mismo id."""
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tipster.pagar(pago, "paid")
    assert _webhook(client, tipster.aviso(pago, "ok", firma="f" * 64)).status_code == 401

    assert _webhook(client, tipster.aviso(pago, "ok")).json() == {"status": "processed"}
    assert _tiene_acceso(client, token)


def test_evento_duplicado_otorga_un_solo_periodo(client, db, tipster, outbox) -> None:
    """§3.9: idempotencia por (pasarela, id de evento)."""
    token, user_id, correo = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    outbox.clear()
    tipster.pagar(pago, "paid")
    aviso = tipster.aviso(pago, "ok")

    assert _webhook(client, aviso).json() == {"status": "processed"}
    [suscripcion] = _suscripciones(db, user_id)
    vence, eventos = suscripcion.current_period_end, _eventos(db)

    for _ in range(3):
        r = _webhook(client, aviso)
        assert (r.status_code, r.json()) == (200, {"status": "duplicate"})

    [suscripcion] = _suscripciones(db, user_id)
    assert suscripcion.current_period_end == vence
    assert _eventos(db) == eventos
    assert len(_pagos(db, user_id)) == 1
    assert len(_asuntos(outbox, correo)) == 2  # una bienvenida y un recibo


def test_dos_avisos_distintos_de_la_misma_orden_un_solo_periodo(client, db, tipster, outbox) -> None:
    """La segunda capa: el pago se resuelve una sola vez, llegue lo que llegue.
    Un `ko` tardio de una orden pagada tampoco lo mueve: gana la reconsulta."""
    token, user_id, correo = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    outbox.clear()
    tipster.pagar(pago, "paid")

    assert _webhook(client, tipster.aviso(pago, "ok")).status_code == 200
    vence = _suscripciones(db, user_id)[0].current_period_end
    r = _webhook(client, tipster.aviso(pago, "ko"))
    assert (r.status_code, r.json()) == (200, {"status": "processed"})

    assert _suscripciones(db, user_id)[0].current_period_end == vence
    assert _pagos(db, user_id)[0].status == "approved"
    assert len(_asuntos(outbox, correo)) == 2


def test_transaccion_declinada_no_concede_acceso(client, db, tipster, outbox) -> None:
    """§3.9."""
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    outbox.clear()
    tipster.pagar(pago, "error")
    r = _webhook(client, tipster.aviso(pago, "ko"))
    assert r.status_code == 200, r.text

    [pago] = _pagos(db, user_id)
    assert (pago.status, pago.failure_reason) == ("declined", "Tipster Page: error")
    assert (pago.period_start, pago.period_end) == (None, None)
    [suscripcion] = _suscripciones(db, user_id)
    assert (suscripcion.status, suscripcion.current_period_end) == ("pending", None)
    assert not _tiene_acceso(client, token)
    assert outbox == []


@pytest.mark.parametrize(
    ("estado", "queda"),
    [
        ("error", "declined"),
        ("expired", "declined"),
        ("error_and_refund_payment", "declined"),
        ("fraud", "error"),
        ("pending", "pending"),
    ],
)
def test_aviso_valido_pero_la_reconsulta_dice_otra_cosa(client, db, tipster, estado, queda) -> None:
    """§3.9: el aviso dice `ok` con firma valida; la reconsulta, no. Gana la reconsulta."""
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tipster.pagar(pago, estado)
    r = _webhook(client, tipster.aviso(pago, "ok"))
    assert r.status_code == 200, r.text

    [pago] = _pagos(db, user_id)
    assert pago.status == queda
    assert _suscripciones(db, user_id)[0].status == "pending"
    assert not _tiene_acceso(client, token)


def test_evento_de_una_referencia_desconocida_se_guarda_y_no_mueve_nada(client, db, tipster) -> None:
    """§3.9."""
    token, user_id, _ = _cuenta(client, db)
    _abrir_pago(client, db, token)
    ajena = f"AJENA-{uuid.uuid4().hex[:8]}"
    tipster.pagar(ajena, "paid")

    r = _webhook(client, tipster.aviso(ajena, "ok"))
    assert (r.status_code, r.json()) == (200, {"status": "ignored"})

    guardado = db.scalar(
        select(PaymentEvent).where(PaymentEvent.provider_event_id == f"tipsterpage:{ajena}:ok")
    )
    assert guardado.signature_verified is True
    assert (guardado.subscription_id, guardado.payment_id) == (None, None)
    assert guardado.processed_at is not None
    assert [p.status for p in _pagos(db, user_id)] == ["pending"]
    assert not _tiene_acceso(client, token)


def test_aviso_de_una_orden_que_la_pasarela_no_conoce(client, db, tipster) -> None:
    """La reconsulta responde 404: no hay nada que aplicar."""
    token, _, _ = _cuenta(client, db)
    _abrir_pago(client, db, token)
    r = _webhook(client, tipster.aviso("SA-que-no-existe", "ok"))
    assert (r.status_code, r.json()) == (200, {"status": "ignored"})
    assert not _tiene_acceso(client, token)


def test_aprobada_por_otro_monto_no_concede_acceso(client, db, tipster) -> None:
    """Una orden pagada por menos de lo que se pidio cobrar."""
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tipster.pagar(pago, "paid", amount=100)
    assert _webhook(client, tipster.aviso(pago, "ok")).status_code == 200

    [pago] = _pagos(db, user_id)
    assert pago.status == "error" and "100" in pago.failure_reason
    assert not _tiene_acceso(client, token)


def test_si_la_pasarela_no_responde_el_evento_queda_para_el_reintento(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tipster.pagar(pago, "paid")
    aviso = tipster.aviso(pago, "ok")

    tipster.caido = True
    assert _webhook(client, aviso).status_code == 502
    assert not _tiene_acceso(client, token)
    guardado = db.scalar(
        select(PaymentEvent).where(PaymentEvent.provider_event_id == f"tipsterpage:{pago.reference}:ok")
    )
    assert guardado.signature_verified is True and guardado.processed_at is None

    # La pasarela reintenta el mismo aviso: ahora si se procesa.
    tipster.caido = False
    assert _webhook(client, aviso).json() == {"status": "processed"}
    assert _tiene_acceso(client, token)
    assert len(_pagos(db, user_id)) == 1


@pytest.mark.parametrize(
    "cuerpo",
    [
        b"",
        b"no es json",
        b"[]",
        b'{"paid_status": "ok"}',
        b'{"paid_status": "ok", "order_id": "x", "amount": 1, "nt_signature": "00"}',
        b'{"paid_status": 1, "order_id": "x", "amount": 1, "nt_signature": "00"}',
    ],
)
def test_un_cuerpo_que_no_es_un_aviso_se_rechaza(client, tipster, cuerpo: bytes) -> None:
    r = client.post("/webhooks/payments", content=cuerpo, headers={"Content-Type": "application/json"})
    assert r.status_code == 401


def test_sin_pasarela_el_webhook_no_acepta_nada(client, db) -> None:
    r = client.post("/webhooks/payments", content=b"{}", headers={"Content-Type": "application/json"})
    assert r.status_code == 401


# ---------- Redencion del cupon ----------


def test_un_pago_aprobado_registra_una_sola_redencion(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db)
    cupon = _cupon(db, value=25, max_redemptions=5)
    pago = _abrir_pago(client, db, token, codigo=cupon.code)
    tipster.pagar(pago, "paid")

    aviso = tipster.aviso(pago, "ok")
    for _ in range(2):
        assert _webhook(client, aviso).status_code == 200
    # Un `ko` de la misma orden, y la consulta del estado del pago.
    assert _webhook(client, tipster.aviso(pago, "ko")).status_code == 200
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


def test_un_pago_declinado_no_redime_el_cupon(client, db, tipster) -> None:
    token, _, _ = _cuenta(client, db)
    cupon = _cupon(db)
    pago = _abrir_pago(client, db, token, codigo=cupon.code)
    tipster.pagar(pago, "error")
    _webhook(client, tipster.aviso(pago, "ko"))

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
    client, db, tipster, campos, quedan
) -> None:
    """Las renovaciones descuentan de aqui."""
    token, user_id, _ = _cuenta(client, db)
    cupon = _cupon(db, **campos)
    _aprobar(client, tipster, _abrir_pago(client, db, token, codigo=cupon.code))
    assert _suscripciones(db, user_id)[0].discount_periods_remaining == quedan


# ---------- GET /billing/payments/:id ----------


def test_la_consulta_del_pago_reconsulta_si_el_aviso_no_ha_llegado(client, db, tipster, outbox) -> None:
    """§3.4: las dos vias pasan por la misma funcion. Con Tipster Page se
    reconsulta con la referencia: la URL de regreso no trae un id."""
    token, user_id, correo = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    outbox.clear()

    r = client.get(f"/billing/payments/{pago.id}", headers=auth(token))
    assert (r.status_code, r.json()["status"]) == (200, "pending")
    assert r.json()["plan_name"] == "Acceso Mensual"

    # El cliente vuelve de la pasarela; el aviso todavia no llega.
    tipster.pagar(pago, "paid")
    r = client.get(f"/billing/payments/{pago.id}", headers=auth(token))
    data = r.json()
    assert (r.status_code, data["status"]) == (200, "approved")
    assert data["period_end"] is not None and data["amount_cents"] == PRECIO
    assert _tiene_acceso(client, token)
    assert len(_asuntos(outbox, correo)) == 2

    # Despues llega el aviso: no da otro periodo ni otro correo.
    vence = _suscripciones(db, user_id)[0].current_period_end
    assert _webhook(client, tipster.aviso(pago, "ok")).status_code == 200
    assert _suscripciones(db, user_id)[0].current_period_end == vence
    assert len(_asuntos(outbox, correo)) == 2


def test_un_id_que_manda_el_navegador_no_cambia_lo_que_se_reconsulta(client, db, tipster) -> None:
    """`transaction_id` viene del navegador: con Tipster Page se ignora y se
    reconsulta la orden de este pago."""
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    otro_token, otro_id, _ = _cuenta(client, db)
    pago_ajeno = _abrir_pago(client, db, otro_token)
    tipster.pagar(pago_ajeno, "paid")

    r = client.get(
        f"/billing/payments/{pago.id}",
        params={"transaction_id": pago_ajeno.reference},
        headers=auth(token),
    )
    assert r.json()["status"] == "pending"
    assert not _tiene_acceso(client, token)
    # Tampoco le activo nada al dueno de esa orden por una consulta ajena.
    assert [p.status for p in _pagos(db, otro_id)] == ["pending"]


def test_un_pago_ajeno_no_se_ve(client, db, tipster) -> None:
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    otro_token, _, _ = _cuenta(client, db)
    assert client.get(f"/billing/payments/{pago.id}", headers=auth(otro_token)).status_code == 404
    assert client.get(f"/billing/payments/{uuid.uuid4()}", headers=auth(token)).status_code == 404
    assert client.get(f"/billing/payments/{pago.id}").status_code == 401


def test_si_la_pasarela_no_responde_la_consulta_dice_pendiente(client, db, tipster) -> None:
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tipster.pagar(pago, "paid")
    tipster.caido = True
    r = client.get(f"/billing/payments/{pago.id}", headers=auth(token))
    assert (r.status_code, r.json()["status"]) == (200, "pending")


def test_un_pago_aprobado_no_se_reconsulta(client, db, tipster) -> None:
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    _aprobar(client, tipster, pago)
    consultas = tipster.consultas
    assert client.get(f"/billing/payments/{pago.id}", headers=auth(token)).json()["status"] == "approved"
    assert tipster.consultas == consultas


# ---------- El periodo siguiente ----------


def test_pagar_antes_del_vencimiento_extiende_desde_el_vencimiento(client, db, tipster, outbox) -> None:
    """Decidido el 2026-10-13: no se pierden los dias que quedaban."""
    token, user_id, correo = _cuenta(client, db)
    _aprobar(client, tipster, _abrir_pago(client, db, token))
    [suscripcion] = _suscripciones(db, user_id)
    inicio, vence = suscripcion.current_period_start, suscripcion.current_period_end
    outbox.clear()

    # El precio del plan sube: la suscripcion vigente paga su precio congelado (§3.7).
    db.execute(text("UPDATE plans SET price_cents = 4000 WHERE code = 'mensual'"))
    db.commit()
    try:
        segundo = _abrir_pago(client, db, token)
        assert (segundo.kind, segundo.amount_cents) == ("renewal", PRECIO)
        _aprobar(client, tipster, segundo)
    finally:
        db.execute(text("UPDATE plans SET price_cents = :p WHERE code = 'mensual'"), {"p": PRECIO})
        db.commit()

    [suscripcion] = _suscripciones(db, user_id)
    assert suscripcion.status == "active"
    assert suscripcion.current_period_start == inicio
    assert suscripcion.current_period_end == add_interval(vence, "month", 1)
    segundo = _pagos(db, user_id)[1]
    assert (segundo.period_start, segundo.period_end) == (vence, add_interval(vence, "month", 1))
    # Solo el recibo: la bienvenida va una vez.
    assert _asuntos(outbox, correo) == ["Recibo de tu pago en Sebasanálisis"]


def test_pagar_despues_del_vencimiento_cuenta_desde_el_pago(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db)
    _aprobar(client, tipster, _abrir_pago(client, db, token))
    vencio = datetime.now(UTC) - timedelta(days=10)
    db.execute(
        text("UPDATE subscriptions SET current_period_end = :e WHERE user_id = :u"),
        {"e": vencio, "u": user_id},
    )
    db.commit()
    assert not _tiene_acceso(client, token)

    antes = datetime.now(UTC)
    _aprobar(client, tipster, _abrir_pago(client, db, token))
    # La que vencio queda como historia; la nueva es la que cuenta.
    [suscripcion] = [s for s in _suscripciones(db, user_id) if s.status != "expired"]
    assert suscripcion.current_period_start >= antes
    assert suscripcion.current_period_end == add_interval(suscripcion.current_period_start, "month", 1)
    assert _tiene_acceso(client, token)


def test_con_el_periodo_vencido_se_puede_volver_con_otro_plan(client, db, tipster) -> None:
    """Volver despues de vencido es un alta nueva: otro plan, y al precio de hoy."""
    token, user_id, _ = _cuenta(client, db)
    _aprobar(client, tipster, _abrir_pago(client, db, token))
    db.execute(
        text("UPDATE subscriptions SET current_period_end = :e WHERE user_id = :u"),
        {"e": datetime.now(UTC) - timedelta(days=2), "u": user_id},
    )
    db.commit()
    bimestral = db.scalar(select(Plan).where(Plan.code == "bimestral"))

    pago = _abrir_pago(client, db, token, bimestral)
    assert (pago.kind, pago.amount_cents) == ("initial", PRECIO_BIMESTRAL)
    # La que vencio queda como historia, vencida; la nueva espera el pago.
    assert sorted((s.status, s.plan_id) for s in _suscripciones(db, user_id)) == sorted(
        [("expired", _mensual(db).id), ("pending", bimestral.id)]
    )

    _aprobar(client, tipster, pago)
    [suscripcion] = [s for s in _suscripciones(db, user_id) if s.status != "expired"]
    assert (suscripcion.status, suscripcion.plan_id, suscripcion.price_cents) == (
        "active",
        bimestral.id,
        PRECIO_BIMESTRAL,
    )
    assert suscripcion.current_period_end == add_interval(suscripcion.current_period_start, "month", 2)
    assert _tiene_acceso(client, token)


def test_con_suscripcion_pagada_no_se_paga_otro_plan_ni_se_usa_cupon(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db)
    _aprobar(client, tipster, _abrir_pago(client, db, token))
    bimestral = db.scalar(select(Plan).where(Plan.code == "bimestral"))

    r = _suscribir(client, token, bimestral.id)
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "other_plan")
    r = _suscribir(client, token, _mensual(db).id, _cupon(db).code)
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "coupon_only_on_first_payment")
    assert len(_pagos(db, user_id)) == 1


def test_un_pago_que_no_se_completo_se_puede_cambiar_por_otro_plan(client, db, tipster) -> None:
    """Abrio el pago del mensual, se devolvio y eligio el de dos meses: una
    sola suscripcion pendiente. Lo que se compra lo dice el pago aprobado."""
    token, user_id, _ = _cuenta(client, db)
    bimestral = db.scalar(select(Plan).where(Plan.code == "bimestral"))
    primero = _abrir_pago(client, db, token)
    _abrir_pago(client, db, token, bimestral)

    [suscripcion] = _suscripciones(db, user_id)
    assert (suscripcion.status, suscripcion.plan_id) == ("pending", bimestral.id)

    # Termina pagando el primero, que seguia abierto en otra pestana.
    _aprobar(client, tipster, primero)
    [suscripcion] = _suscripciones(db, user_id)
    assert (suscripcion.plan_id, suscripcion.price_cents) == (_mensual(db).id, PRECIO)
    assert suscripcion.current_period_end == add_interval(suscripcion.current_period_start, "month", 1)


def test_la_base_no_admite_dos_suscripciones_vivas_por_cuenta(client, db, tipster) -> None:
    """§3.4: la restriccion vive en la base, no solo en el codigo."""
    token, user_id, _ = _cuenta(client, db)
    _abrir_pago(client, db, token)
    plan = _mensual(db)
    for estado in ("pending", "active", "past_due"):
        db.add(
            Subscription(
                user_id=uuid.UUID(user_id),
                plan_id=plan.id,
                provider="tipsterpage",
                status=estado,
                price_cents=PRECIO,
                currency="EUR",
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
            provider="tipsterpage",
            status="expired",
            price_cents=PRECIO,
            currency="EUR",
        )
    )
    db.commit()


# ---------- GET /billing/subscription ----------


def test_la_suscripcion_de_la_cuenta(client, db, tipster) -> None:
    token, _, _ = _cuenta(client, db)
    assert client.get("/billing/subscription").status_code == 401
    assert client.get("/billing/subscription", headers=auth(token)).json() is None

    pago = _abrir_pago(client, db, token)
    # Una que nunca se pago no cuenta.
    assert client.get("/billing/subscription", headers=auth(token)).json() is None

    _aprobar(client, tipster, pago)
    data = client.get("/billing/subscription", headers=auth(token)).json()
    assert (data["status"], data["renewal_mode"], data["price_cents"], data["currency"]) == (
        "active",
        "manual",
        PRECIO,
        "EUR",
    )
    assert data["plan"]["code"] == "mensual"
    assert data["current_period_end"] is not None and data["cancel_at_period_end"] is False
    assert data["in_force"] is True


# ---------- Eliminar la cuenta ----------


def test_eliminar_la_cuenta_conserva_el_pago_sin_usuario(client, db, tipster) -> None:
    """Decidido el 2026-10-13. Lo que hacen las llaves; el resto del cierre de
    la cuenta esta en `test_subscription_changes.py`."""
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    _aprobar(client, tipster, pago)
    pago_id = pago.id

    r = client.request(
        "DELETE", "/auth/me", json={"password": "clave-segura-123"}, headers=auth(token)
    )
    assert r.status_code == 204, r.text

    db.expire_all()
    assert _suscripciones(db, user_id) == []
    conservado = db.get(Payment, pago_id)
    assert (conservado.user_id, conservado.subscription_id) == (None, None)
    assert (conservado.status, conservado.amount_cents, conservado.currency) == ("approved", PRECIO, "EUR")
    evento = db.scalar(select(PaymentEvent).where(PaymentEvent.payment_id == pago_id))
    assert evento is not None and evento.subscription_id is None


# ---------- Pasarela simulada ----------


def test_la_pasarela_simulada_no_existe_con_otra_pasarela(client, db, tipster) -> None:
    r = client.post(
        "/dev/fake-checkout",
        data={
            "reference": "x",
            "amount_cents": 1,
            "currency": "EUR",
            "url_ok": "http://localhost:3000/pago/1",
            "url_ko": "http://localhost:3000/pago/1",
            "outcome": "approved",
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
        # Su catalogo: la tarjeta simulada en cualquier pais, el medio local en Colombia.
        r = client.get("/billing/payment-methods", headers=auth(token))
        assert [m["key"] for m in r.json()] == ["fakecard"]
        r = client.get("/billing/payment-methods", params={"country": "CO"}, headers=auth(token))
        assert [(m["key"], m["fields"]) for m in r.json()] == [
            ("fakecard", []),
            ("fakelocal", ["first_name"]),
        ]

        r = _suscribir(client, token, _mensual(db).id, metodo="fakecard")
        assert r.status_code == 202, r.text
        url = httpx.URL(r.json()["checkout_url"])
        pagina = client.get(url.path)
        assert pagina.status_code == 200 and "Pasarela simulada" in pagina.text
        assert "form-action 'self'" in pagina.headers["content-security-policy"]

        pago = _pagos(db, user_id)[0]
        datos = {
            "reference": pago.reference,
            "amount_cents": pago.amount_cents,
            "currency": pago.currency,
            "url_ok": f"http://localhost:3000/pago/{pago.id}",
            "url_ko": f"http://localhost:3000/pago/{pago.id}",
        }
        # Solo devuelve al frontend de esta instalacion.
        r = client.post(
            "/dev/fake-checkout",
            data={**datos, "url_ok": "https://otro-sitio.com/x", "outcome": "approved"},
            follow_redirects=False,
        )
        assert r.status_code == 400

        r = client.post(
            "/dev/fake-checkout", data={**datos, "outcome": "approved"}, follow_redirects=False
        )
        assert r.status_code == 303
        regreso = httpx.URL(r.headers["location"])
        assert regreso.path == f"/pago/{pago.id}"

        consulta = client.get(
            f"/billing/payments/{pago.id}",
            params={"transaction_id": regreso.params["id"]},
            headers=auth(token),
        )
        assert consulta.json()["status"] == "approved"
        assert _tiene_acceso(client, token)

        # Su webhook exige su propia marca: sin ella, se rechaza.
        cuerpo = json.dumps({"id": "evt-1", "transaction_id": regreso.params["id"]})
        assert client.post("/webhooks/payments", content=cuerpo).status_code == 401
        r = client.post(
            "/webhooks/payments", content=cuerpo, headers={FAKE_SIGNATURE_HEADER: FAKE_SIGNATURE}
        )
        assert r.status_code == 200
    finally:
        app.dependency_overrides[get_payment_provider] = anterior


def test_las_ordenes_de_la_pasarela_no_se_mezclan_con_las_de_otro_test() -> None:
    """El Tipster Page simulado es por test: no hay estado compartido."""
    assert TipsterSandbox().ordenes == {}


def test_coupon_no_se_reutiliza_en_dos_cuentas_mas_alla_del_tope(client, db, tipster) -> None:
    """El tope de usos se revisa al abrir el pago."""
    cupon = _cupon(db, max_redemptions=1)
    token_a, _, _ = _cuenta(client, db)
    _aprobar(client, tipster, _abrir_pago(client, db, token_a, codigo=cupon.code))
    token_b, _, _ = _cuenta(client, db)
    r = _suscribir(client, token_b, _mensual(db).id, cupon.code)
    assert (r.status_code, r.json()["detail"]["reason"]) == (400, "exhausted")
    assert db.get(Coupon, cupon.id).redemptions_count == 1


# ---------- Cupones y pagos abiertos a la vez (auditoria del 2026-11-12) ----------

_LOGGER = "app.core.subscriptions"


def _abandonar(db, payment: Payment) -> None:
    """Deja el pago como una orden abandonada: mas vieja que la ventana de pagos
    pendientes (`schedule.PENDING_PAYMENT_WINDOW`)."""
    db.execute(
        text("UPDATE payments SET created_at = now() - interval '8 days' WHERE id = :id"),
        {"id": payment.id},
    )
    db.commit()


def test_un_pago_abierto_con_cupon_reserva_un_cupo_del_tope(client, db, tipster) -> None:
    """Decidido por el usuario el 2026-11-12: un pago abierto con cupon reserva
    un cupo del tope. La misma cuenta puede reintentar con el cupon (el pago
    nuevo reemplaza al abandonado); otra cuenta no, hasta que la orden venza."""
    cupon = _cupon(db, max_redemptions=1)
    token_a, _, _ = _cuenta(client, db)
    primero = _abrir_pago(client, db, token_a, codigo=cupon.code)

    token_b, user_b, _ = _cuenta(client, db)
    r = _suscribir(client, token_b, _mensual(db).id, cupon.code)
    assert (r.status_code, r.json()["detail"]["reason"]) == (400, "exhausted")
    assert client.post(
        "/billing/quote",
        json={"plan_id": str(_mensual(db).id), "coupon_code": cupon.code},
        headers=auth(token_b),
    ).json()["coupon"]["reason"] == "exhausted"

    # La misma cuenta reintenta con el mismo cupon: se le deja.
    assert _abrir_pago(client, db, token_a, codigo=cupon.code).discount_cents > 0

    # Vencida la orden de la primera cuenta, el cupo vuelve a estar libre.
    for pago in _pagos(db, str(primero.user_id)):
        _abandonar(db, pago)
    assert _abrir_pago(client, db, token_b, codigo=cupon.code).discount_cents > 0
    db.expire_all()
    assert db.get(Coupon, cupon.id).redemptions_count == 0


def test_dos_pagos_aprobados_con_el_mismo_cupon_avisan(client, db, tipster, caplog) -> None:
    """Si aun asi se pagan los dos, el dinero salio: se concede el periodo, el
    cupon se cuenta una vez y queda un error para que lo revise el admin."""
    token, user_id, _ = _cuenta(client, db)
    cupon = _cupon(db, value=50)
    a = _abrir_pago(client, db, token, codigo=cupon.code)
    b = _abrir_pago(client, db, token, codigo=cupon.code)

    _aprobar(client, tipster, a)
    with caplog.at_level("ERROR", logger=_LOGGER):
        _aprobar(client, tipster, b)

    assert [p.status for p in _pagos(db, user_id)] == ["approved", "approved"]
    db.expire_all()
    assert db.get(Coupon, cupon.id).redemptions_count == 1
    assert any(
        str(b.id) in r.getMessage() and cupon.code in r.getMessage() for r in caplog.records
    ), caplog.text


def test_un_cupon_que_pasa_su_tope_al_aprobarse_avisa(client, db, tipster, caplog) -> None:
    """Una orden dada por abandonada que la pasarela aprueba despues: el cupon
    ya se reservo para otra cuenta. Se cuenta igual y queda el aviso."""
    cupon = _cupon(db, max_redemptions=1)
    token_a, _, _ = _cuenta(client, db)
    tardio = _abrir_pago(client, db, token_a, codigo=cupon.code)
    _abandonar(db, tardio)
    token_b, _, _ = _cuenta(client, db)
    _aprobar(client, tipster, _abrir_pago(client, db, token_b, codigo=cupon.code))

    with caplog.at_level("ERROR", logger=_LOGGER):
        _aprobar(client, tipster, tardio)

    db.expire_all()
    assert db.get(Coupon, cupon.id).redemptions_count == 2
    assert any(
        str(tardio.id) in r.getMessage() and cupon.code in r.getMessage() for r in caplog.records
    ), caplog.text


def test_una_renovacion_con_descuento_agotado_avisa(client, db, tipster, caplog) -> None:
    """Dos renovaciones manuales abiertas con el ultimo periodo con descuento:
    las dos se cotizan con el; la segunda que se aprueba deja el aviso."""
    token, user_id, _ = _cuenta(client, db)
    cupon = _cupon(db, value=50, duration="repeating", duration_periods=2)
    _aprobar(client, tipster, _abrir_pago(client, db, token, codigo=cupon.code))
    [suscripcion] = _suscripciones(db, user_id)
    assert suscripcion.discount_periods_remaining == 1

    r1 = _abrir_pago(client, db, token)
    r2 = _abrir_pago(client, db, token)
    assert r1.discount_cents > 0 and r2.discount_cents > 0
    _aprobar(client, tipster, r1)
    with caplog.at_level("ERROR", logger=_LOGGER):
        _aprobar(client, tipster, r2)

    assert any(str(r2.id) in r.getMessage() for r in caplog.records), caplog.text


# ---------- Historial de pagos de la cuenta (GET /billing/payments) ----------


def test_historial_de_pagos_de_la_cuenta(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db)
    assert client.get("/billing/payments").status_code == 401
    assert client.get("/billing/payments", headers=auth(token)).json() == {
        "items": [],
        "total": 0,
        "limit": 20,
        "offset": 0,
    }

    rechazado = _abrir_pago(client, db, token)
    tipster.pagar(rechazado, "error")
    _webhook(client, tipster.aviso(rechazado, "ko"))
    aprobado = _abrir_pago(client, db, token)
    _aprobar(client, tipster, aprobado)
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
        "EUR",
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


def test_admin_ve_la_suscripcion_y_los_pagos_de_una_cuenta(client, db, tipster, admin_token) -> None:
    token, user_id, _ = _cuenta(client, db)
    detalle = client.get(f"/admin/users/{user_id}", headers=auth(admin_token)).json()
    assert (detalle["subscription"], detalle["payments"]) == (None, [])

    rechazado = _abrir_pago(client, db, token)
    tipster.pagar(rechazado, "error")
    _webhook(client, tipster.aviso(rechazado, "ko"))
    aprobado = _abrir_pago(client, db, token)
    _aprobar(client, tipster, aprobado)
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
    assert (visto["reference"], visto["provider_transaction_id"]) == (
        aprobado.reference,
        aprobado.reference,
    )
    assert detalle["payments"][2]["failure_reason"] == "Tipster Page: error"

    # Solo un administrador.
    assert client.get(f"/admin/users/{user_id}", headers=auth(token)).status_code == 403


def test_admin_filtra_las_cuentas_por_suscripcion(client, db, tipster, admin_token) -> None:
    def filtrar(valor: str, correo: str) -> list[str]:
        r = client.get(
            "/admin/users",
            params={"subscription": valor, "query": correo},
            headers=auth(admin_token),
        )
        assert r.status_code == 200, r.text
        return [u["email"] for u in r.json()["items"]]

    # Vigente.
    t_vigente, _, vigente = _cuenta(client, db)
    _aprobar(client, tipster, _abrir_pago(client, db, t_vigente))
    # Vencida: pago y el periodo ya paso.
    t_vencida, id_vencida, vencida = _cuenta(client, db)
    _aprobar(client, tipster, _abrir_pago(client, db, t_vencida))
    db.execute(
        text("UPDATE subscriptions SET current_period_end = :e WHERE user_id = :u"),
        {"e": datetime.now(UTC) - timedelta(days=1), "u": id_vencida},
    )
    db.commit()
    # Pago sin completar.
    t_pendiente, _, pendiente = _cuenta(client, db)
    _abrir_pago(client, db, t_pendiente)
    # Nunca abrio un pago.
    _, _, ninguna = _cuenta(client, db)

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
