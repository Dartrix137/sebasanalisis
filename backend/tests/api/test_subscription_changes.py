"""Gestion de una suscripcion ya pagada y cierre de la cuenta (§3.6, §3.10 y §5.4 de la Fase 4).

Cambiar el medio de pago, pasar de un modo de pago al otro, y lo que queda de
los pagos al eliminar la cuenta. Wompi es el doble de `wompi_double.py`; el job
de renovaciones se llama directo con el `now` que cada caso necesita.
"""

import pytest
from sqlalchemy import select, text

from app.billing.periods import add_interval
from app.models import Coupon, CouponRedemption, Payment, PaymentEvent
from tests.api.conftest import auth
from tests.api.test_billing import _cupon, _mensual
from tests.api.test_renewals import (
    DIA,
    H,
    _avisada,
    _correr,
    _de,
    _suscripcion,
    _suscriptor_automatico,
)
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
from tests.api.wompi_double import (
    ACEPTACION,
    DATOS_PERSONALES,
    TOKEN_NEQUI,
    TOKEN_RECHAZADO,
    TOKEN_TARJETA,
    Wompi,
)

CLAVE = "clave-segura-123"
CAMBIO = "Cambió el medio de pago de tu suscripción a Sebasanálisis"
A_MANUAL = "Tu suscripción a Sebasanálisis pasó a pago manual"


@pytest.fixture(autouse=True)
def sin_suscripciones_de_otros_tests(db) -> None:
    """El job recorre TODAS las suscripciones de la base: cada test empieza sin
    las de los demas."""
    for tabla in ("payment_events", "payments", "coupon_redemptions", "subscriptions"):
        db.execute(text(f"DELETE FROM {tabla}"))
    db.commit()


def _guardar_medio(client, token: str | None, **cambios):
    body = {
        "payment_source_token": TOKEN_TARJETA,
        "payment_source_type": "CARD",
        "acceptance_token": ACEPTACION,
        "personal_data_token": DATOS_PERSONALES,
        **cambios,
    }
    return client.put("/billing/payment-method", json=body, headers=auth(token) if token else {})


def _suscriptor_manual(client, db, wompi: Wompi) -> tuple[str, str, str]:
    token, user_id, correo = _cuenta(client, db)
    _aprobar(client, wompi, _abrir_pago(client, db, token))
    return token, user_id, correo


def _eliminar(client, token: str):
    return client.request("DELETE", "/auth/me", json={"password": CLAVE}, headers=auth(token))


# ---------- Cambiar el medio de pago ----------


def test_cambiar_la_tarjeta_no_cobra_y_el_siguiente_cobro_va_a_la_nueva(
    client, db, wompi, outbox
) -> None:
    token, user_id, correo, suscripcion = _suscriptor_automatico(client, db, wompi)
    vence = suscripcion.current_period_end
    assert suscripcion.payment_source_id == "3000"
    outbox.clear()

    assert _guardar_medio(client, None).status_code == 401
    r = _guardar_medio(client, token)
    assert r.status_code == 200, r.text
    data = r.json()
    assert (data["status"], data["renewal_mode"], data["card_last4"]) == ("active", "automatic", "4242")
    assert data["next_charge_cents"] == PRECIO

    # A Wompi se le pidio guardar el medio nuevo, con los dos contratos, y nada mas:
    # el periodo vigente ya estaba pagado.
    assert wompi.fuentes_pedidas[-1] == {
        "type": "CARD",
        "token": TOKEN_TARJETA,
        "customer_email": correo,
        "acceptance_token": ACEPTACION,
        "accept_personal_auth": DATOS_PERSONALES,
    }
    assert len(wompi.cobros) == 1
    suscripcion = _suscripcion(db, user_id)
    assert (suscripcion.payment_source_id, suscripcion.current_period_end) == ("3001", vence)
    assert suscripcion.next_charge_at == vence - 48 * H

    [correo_cambio] = [m for m in outbox if m.to == correo]
    assert correo_cambio.subject == CAMBIO
    assert "Cambiaste el medio de pago" in correo_cambio.text
    assert "Hoy no te cobramos nada" in correo_cambio.text and "100.000 COP" in correo_cambio.text
    # Ni el token ni nada parecido a un numero de tarjeta.
    assert TOKEN_TARJETA not in correo_cambio.text

    # La renovacion se le cobra a la fuente nueva.
    _avisada(db, wompi, suscripcion)
    assert _correr(db, wompi, vence - 48 * H).approved == 1
    assert wompi.cobros[-1]["payment_source_id"] == 3001
    assert _suscripcion(db, user_id).card_brand == "VISA"


def test_cambiar_a_nequi(client, db, wompi) -> None:
    token, user_id, _, _ = _suscriptor_automatico(client, db, wompi)
    r = _guardar_medio(
        client, token, payment_source_token=TOKEN_NEQUI, payment_source_type="NEQUI"
    )
    assert r.status_code == 200, r.text
    suscripcion = _suscripcion(db, user_id)
    assert (suscripcion.payment_source_type, suscripcion.card_brand, suscripcion.card_last4) == (
        "NEQUI",
        None,
        None,
    )


def test_un_medio_que_wompi_no_acepta_deja_todo_como_estaba(client, db, wompi, outbox) -> None:
    token, user_id, correo, _ = _suscriptor_automatico(client, db, wompi)
    outbox.clear()
    r = _guardar_medio(client, token, payment_source_token=TOKEN_RECHAZADO)
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "payment_source_rejected")
    assert _suscripcion(db, user_id).payment_source_id == "3000"
    assert _asuntos(outbox, correo) == []

    wompi.caido = True
    r = _guardar_medio(client, token)
    assert (r.status_code, r.json()["detail"]["code"]) == (502, "provider_unavailable")
    assert _suscripcion(db, user_id).payment_source_id == "3000"


def test_sin_un_periodo_pagado_no_hay_donde_guardar_el_medio(client, db, wompi) -> None:
    token, _, _ = _cuenta(client, db)
    r = _guardar_medio(client, token)
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "no_subscription")
    # Con un pago abierto sin completar, tampoco.
    _abrir_pago(client, db, token)
    r = _guardar_medio(client, token)
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "no_subscription")
    assert wompi.fuentes_pedidas == []

    r = client.delete("/billing/payment-method", headers=auth(token))
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "no_subscription")


def test_guardar_un_medio_exige_el_token_y_los_dos_contratos(client, db, wompi) -> None:
    token, _, _, _ = _suscriptor_automatico(client, db, wompi)
    for campo in ("payment_source_token", "acceptance_token", "personal_data_token"):
        assert _guardar_medio(client, token, **{campo: ""}).status_code == 422
    assert _guardar_medio(client, token, payment_source_type="PSE").status_code == 422
    assert len(wompi.fuentes_pedidas) == 1


# ---------- De pago manual a renovacion automatica ----------


def test_de_manual_a_automatica_no_cobra_hoy_y_avisa_antes_del_primer_cobro(
    client, db, wompi, outbox
) -> None:
    token, user_id, correo = _suscriptor_manual(client, db, wompi)
    suscripcion = _suscripcion(db, user_id)
    vence = suscripcion.current_period_end

    # Ya le habia llegado el aviso de vencimiento del pago manual.
    reporte = _correr(db, wompi, vence - 6 * DIA)
    assert _de(reporte, correo) == ["Tu acceso a Sebasanálisis está por terminar"]
    outbox.clear()

    r = _guardar_medio(client, token)
    assert r.status_code == 200, r.text
    data = r.json()
    assert (data["status"], data["renewal_mode"]) == ("active", "automatic")
    assert (data["next_charge_cents"], data["current_period_end"] is not None) == (PRECIO, True)
    # No se cobro nada: el periodo vigente ya estaba pagado.
    assert wompi.cobros == []
    suscripcion = _suscripcion(db, user_id)
    assert (suscripcion.payment_source_id, suscripcion.current_period_end) == ("3000", vence)
    assert suscripcion.next_charge_at == vence - 48 * H
    [activada] = [m for m in outbox if m.to == correo]
    assert activada.subject == CAMBIO and "Activaste la renovación automática" in activada.text

    # El aviso del pago manual no vale como aviso del cobro: sale el del cobro
    # automatico, y esa corrida no cobra.
    reporte = _correr(db, wompi, vence - 48 * H)
    assert (reporte.notices, reporte.charges) == (1, 0)
    assert _de(reporte, correo) == ["Aviso: próximo cobro de tu suscripción a Sebasanálisis"]
    reporte = _correr(db, wompi, vence - 47 * H)
    assert (reporte.charges, reporte.approved) == (1, 1)
    assert wompi.cobros[-1]["payment_source_id"] == 3000
    suscripcion = _suscripcion(db, user_id)
    assert suscripcion.current_period_end == add_interval(vence, "month", 1)
    assert _tiene_acceso(client, token)


def test_el_alta_no_sirve_para_cambiar_de_modo_con_un_periodo_pagado(client, db, wompi) -> None:
    """Abrir un pago con renovacion automatica cobraria un periodo: el cambio
    de modo va por `PUT /billing/payment-method`, sin cobro."""
    token, _, _ = _suscriptor_manual(client, db, wompi)
    r = client.post(
        "/billing/subscriptions",
        json={
            "plan_id": str(_mensual(db).id),
            "renewal_mode": "automatic",
            "payment_source_token": TOKEN_TARJETA,
            "payment_source_type": "CARD",
            "acceptance_token": ACEPTACION,
            "personal_data_token": DATOS_PERSONALES,
        },
        headers=auth(token),
    )
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "mode_change_in_account")
    assert wompi.fuentes_pedidas == []


# ---------- De renovacion automatica a pago manual ----------


def test_de_automatica_a_manual_deja_de_cobrar_y_olvida_el_medio(client, db, wompi, outbox) -> None:
    token, user_id, correo, suscripcion = _suscriptor_automatico(client, db, wompi)
    vence = _avisada(db, wompi, suscripcion)
    outbox.clear()

    assert client.delete("/billing/payment-method").status_code == 401
    r = client.delete("/billing/payment-method", headers=auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert (data["status"], data["renewal_mode"], data["in_force"]) == ("active", "manual", True)
    assert (data["next_charge_at"], data["payment_source_type"], data["card_last4"]) == (
        None,
        None,
        None,
    )
    suscripcion = _suscripcion(db, user_id)
    assert (
        suscripcion.payment_source_id,
        suscripcion.payment_source_type,
        suscripcion.card_brand,
        suscripcion.card_last4,
        suscripcion.next_charge_at,
    ) == (None, None, None, None, None)
    assert suscripcion.current_period_end == vence and _tiene_acceso(client, token)
    [aviso] = [m for m in outbox if m.to == correo]
    assert aviso.subject == A_MANUAL
    assert "no te vamos a hacer más cobros automáticos" in aviso.text

    r = client.delete("/billing/payment-method", headers=auth(token))
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "not_automatic")

    # El job ya no cobra: avisa del vencimiento como a cualquier pago manual,
    # aunque el aviso del cobro automatico de este periodo ya hubiera salido.
    reporte = _correr(db, wompi, vence - 48 * H)
    assert (reporte.charges, reporte.notices) == (0, 1)
    assert _de(reporte, correo) == ["Tu acceso a Sebasanálisis está por terminar"]
    assert len(wompi.cobros) == 1

    # Y puede pagar a mano el periodo siguiente.
    pago = _abrir_pago(client, db, token)
    assert pago.kind == "renewal"
    _aprobar(client, wompi, pago, timestamp=1_760_000_500)
    assert _suscripcion(db, user_id).current_period_end == add_interval(vence, "month", 1)


def test_una_renovacion_cancelada_se_puede_reanudar_con_otro_medio(client, db, wompi) -> None:
    token, user_id, _, suscripcion = _suscriptor_automatico(client, db, wompi)
    vence = suscripcion.current_period_end
    assert client.post("/billing/subscription/cancel", headers=auth(token)).status_code == 200
    # Despues de cancelar abrio un pago manual que no completo.
    _abrir_pago(client, db, token)

    r = _guardar_medio(client, token)
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["cancel_at_period_end"]) == ("active", False)
    [suscripcion] = _suscripciones(db, user_id)
    assert (suscripcion.status, suscripcion.payment_source_id) == ("active", "3001")
    assert (suscripcion.canceled_at, suscripcion.next_charge_at) == (None, vence - 48 * H)


def test_una_renovacion_cancelada_tambien_puede_pasar_a_pago_manual(client, db, wompi) -> None:
    token, user_id, _, _ = _suscriptor_automatico(client, db, wompi)
    assert client.post("/billing/subscription/cancel", headers=auth(token)).status_code == 200
    r = client.delete("/billing/payment-method", headers=auth(token))
    assert r.status_code == 200, r.text
    suscripcion = _suscripcion(db, user_id)
    assert (suscripcion.status, suscripcion.renewal_mode, suscripcion.cancel_at_period_end) == (
        "active",
        "manual",
        False,
    )


def test_un_pago_cuya_suscripcion_pendiente_se_descarto_extiende_la_vigente(
    client, db, wompi
) -> None:
    """Cancelo, abrio un pago manual, reanudo (eso descarta la suscripcion
    pendiente) y despues el pago manual se aprobo: el periodo no se pierde."""
    token, user_id, _, suscripcion = _suscriptor_automatico(client, db, wompi)
    vence = suscripcion.current_period_end
    client.post("/billing/subscription/cancel", headers=auth(token))
    pago = _abrir_pago(client, db, token)
    assert client.post("/billing/subscription/resume", headers=auth(token)).status_code == 200

    _aprobar(client, wompi, pago)
    [suscripcion] = _suscripciones(db, user_id)
    assert suscripcion.status == "active"
    assert suscripcion.current_period_end == add_interval(vence, "month", 1)


# ---------- En mora ----------


def test_en_mora_cambiar_el_medio_reintenta_el_cobro_de_inmediato(client, db, wompi, outbox) -> None:
    """§3.6: no espera a la hora del siguiente intento."""
    token, user_id, correo, suscripcion = _suscriptor_automatico(client, db, wompi)
    vence = _avisada(db, wompi, suscripcion)
    wompi.estado_del_cobro = "DECLINED"
    assert _correr(db, wompi, vence - 48 * H).failed == 1
    assert _suscripcion(db, user_id).status == "past_due"
    outbox.clear()

    wompi.estado_del_cobro = "APPROVED"
    r = _guardar_medio(client, token)
    assert r.status_code == 200, r.text
    data = r.json()
    assert (data["status"], data["in_force"]) == ("active", True)

    # Un cobro mas, a la fuente nueva, con la referencia del segundo intento.
    assert len(wompi.cobros) == 3
    assert wompi.cobros[-1]["payment_source_id"] == 3001
    pagos = _pagos(db, user_id)
    assert [(p.kind, p.status) for p in pagos] == [
        ("initial", "approved"),
        ("renewal", "declined"),
        ("renewal", "approved"),
    ]
    assert pagos[1].reference[:-1] == pagos[2].reference[:-1]
    assert (pagos[1].reference[-1], pagos[2].reference[-1]) == ("1", "2")
    suscripcion = _suscripcion(db, user_id)
    assert suscripcion.current_period_end == add_interval(vence, "month", 1)
    assert suscripcion.retry_count == 0
    assert sorted(_asuntos(outbox, correo)) == sorted(
        [CAMBIO, "Recibo de tu pago en Sebasanálisis"]
    )

    # El job no vuelve a cobrar el periodo que ya se pago.
    assert _correr(db, wompi, vence - 24 * H).charges == 0
    assert len(wompi.cobros) == 3


def test_en_mora_los_reintentos_por_cambio_de_medio_no_pasan_de_tres(client, db, wompi) -> None:
    token, user_id, _, suscripcion = _suscriptor_automatico(client, db, wompi)
    vence = _avisada(db, wompi, suscripcion)
    wompi.estado_del_cobro = "DECLINED"
    _correr(db, wompi, vence - 48 * H)

    for _ in range(2):
        r = _guardar_medio(client, token)
        assert (r.status_code, r.json()["status"]) == (200, "past_due")
    assert len(wompi.cobros) == 4  # el inicial y los tres intentos
    # Agotados los tres, guardar otro medio ya no cobra.
    assert _guardar_medio(client, token).status_code == 200
    assert len(wompi.cobros) == 4
    suscripcion = _suscripcion(db, user_id)
    assert (suscripcion.status, suscripcion.current_period_end) == ("past_due", vence)
    assert _tiene_acceso(client, token)
    # Y el job tampoco: vence en su fecha.
    assert _correr(db, wompi, vence - 24 * H).charges == 0
    assert _correr(db, wompi, vence).expired == 1


def test_en_mora_con_un_cobro_todavia_sin_resolver_no_se_cobra_otra_vez(client, db, wompi) -> None:
    token, user_id, _, suscripcion = _suscriptor_automatico(client, db, wompi)
    vence = _avisada(db, wompi, suscripcion)
    wompi.estado_del_cobro = "DECLINED"
    _correr(db, wompi, vence - 48 * H)
    wompi.estado_del_cobro = "PENDING"
    _correr(db, wompi, vence - 24 * H)
    assert len(wompi.cobros) == 3

    assert _guardar_medio(client, token).status_code == 200
    assert len(wompi.cobros) == 3


def test_en_mora_se_puede_pasar_a_pago_manual(client, db, wompi) -> None:
    token, user_id, _, suscripcion = _suscriptor_automatico(client, db, wompi)
    vence = _avisada(db, wompi, suscripcion)
    wompi.estado_del_cobro = "DECLINED"
    _correr(db, wompi, vence - 48 * H)

    assert client.delete("/billing/payment-method", headers=auth(token)).status_code == 200
    suscripcion = _suscripcion(db, user_id)
    assert (suscripcion.status, suscripcion.renewal_mode, suscripcion.retry_count) == (
        "active",
        "manual",
        0,
    )
    assert _correr(db, wompi, vence - 24 * H).charges == 0
    assert _correr(db, wompi, vence).expired == 1


# ---------- Eliminar la cuenta ----------


def test_eliminar_la_cuenta_cancela_la_renovacion_y_conserva_los_pagos_anonimos(
    client, db, wompi, outbox, admin_token
) -> None:
    cupon = _cupon(db)
    cupon_id = cupon.id
    token, user_id, correo, suscripcion = _suscriptor_automatico(
        client, db, wompi, codigo=cupon.code
    )
    vence = suscripcion.current_period_end
    [pago] = _pagos(db, user_id)
    pago_id = pago.id
    # Un evento de ese pago, con los datos personales que manda el proveedor.
    evento = wompi.evento(pago.provider_transaction_id, timestamp=1_760_000_900)
    assert evento["data"]["transaction"]["customer_email"]
    assert _webhook(client, evento).status_code == 200
    outbox.clear()

    assert _eliminar(client, token).status_code == 204

    db.expire_all()
    # La suscripcion se fue, y con ella la referencia del medio de pago.
    assert _suscripciones(db, user_id) == []
    assert db.scalar(text("SELECT count(*) FROM subscriptions")) == 0
    # El pago queda, sin cuenta.
    conservado = db.get(Payment, pago_id)
    assert (conservado.user_id, conservado.subscription_id) == (None, None)
    assert (conservado.status, conservado.currency) == ("approved", "COP")
    # Su evento ya no tiene el correo ni nada del medio de pago.
    guardado = db.scalar(select(PaymentEvent).where(PaymentEvent.payment_id == pago_id))
    assert guardado.raw_payload["anonymized"] is True
    assert guardado.raw_payload["data"]["transaction"]["id"] == pago.provider_transaction_id
    assert "customer_email" not in str(guardado.raw_payload)
    assert correo not in str(guardado.raw_payload) and "4242" not in str(guardado.raw_payload)
    # El uso del cupon sigue contando, sin la cuenta.
    [uso] = db.scalars(select(CouponRedemption).where(CouponRedemption.coupon_id == cupon_id))
    assert (uso.user_id, uso.subscription_id) == (None, None)
    assert db.get(Coupon, cupon_id).redemptions_count == 1
    r = client.get(f"/admin/coupons/{cupon_id}/redemptions", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    assert [(i["user_id"], i["user_email"]) for i in r.json()["items"]] == [(None, None)]

    [despedida] = [m for m in outbox if m.to == correo]
    assert "la renovación automática quedó cancelada" in despedida.text
    assert "no te vamos a hacer ningún cobro más" in despedida.text

    # El job no tiene a quien cobrarle.
    for cuando in (vence - 9 * DIA, vence - 48 * H, vence):
        reporte = _correr(db, wompi, cuando)
        assert (reporte.notices, reporte.charges, reporte.errors, reporte.emails) == (0, 0, 0, [])
    assert len(wompi.cobros) == 1


def test_eliminar_una_cuenta_sin_suscripcion_no_habla_de_pagos(client, db, wompi, outbox) -> None:
    token, _, correo = _cuenta(client, db)
    outbox.clear()
    assert _eliminar(client, token).status_code == 204
    [despedida] = [m for m in outbox if m.to == correo]
    assert "Tu suscripción se eliminó" not in despedida.text and "cobro" not in despedida.text


def test_con_un_cobro_en_proceso_la_cuenta_no_se_elimina_todavia(client, db, wompi) -> None:
    """Si se aprobara despues de borrar, quedaria cobrado sin cuenta."""
    token, user_id, _ = _cuenta(client, db)
    wompi.estado_del_cobro = "PENDING"
    r = client.post(
        "/billing/subscriptions",
        json={
            "plan_id": str(_mensual(db).id),
            "renewal_mode": "automatic",
            "payment_source_token": TOKEN_TARJETA,
            "payment_source_type": "CARD",
            "acceptance_token": ACEPTACION,
            "personal_data_token": DATOS_PERSONALES,
        },
        headers=auth(token),
    )
    assert r.status_code == 202, r.text
    [pago] = _pagos(db, user_id)

    r = _eliminar(client, token)
    assert r.status_code == 409 and "pago en proceso" in r.json()["detail"]
    assert len(_suscripciones(db, user_id)) == 1

    wompi.resolver(pago.provider_transaction_id, "DECLINED")
    assert _webhook(client, wompi.evento(pago.provider_transaction_id)).status_code == 200
    assert _eliminar(client, token).status_code == 204


def test_un_pago_abierto_sin_completar_no_impide_eliminar_y_su_evento_tardio_queda_anonimo(
    client, db, wompi
) -> None:
    token, user_id, correo = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    pago_id = pago.id
    assert _eliminar(client, token).status_code == 204

    # El cliente si pago en la pagina del proveedor, y el evento llega despues.
    tx_id = wompi.transaccion(pago, "APPROVED")
    assert _webhook(client, wompi.evento(tx_id)).status_code == 200
    db.expire_all()
    conservado = db.get(Payment, pago_id)
    # Queda aprobado y sin cuenta: nadie recibe el periodo, y hay que mirarlo a mano.
    assert (conservado.status, conservado.user_id, conservado.period_end) == ("approved", None, None)
    guardado = db.scalar(select(PaymentEvent).where(PaymentEvent.payment_id == pago_id))
    assert guardado.raw_payload["anonymized"] is True
    assert "customer_email" not in str(guardado.raw_payload)


# ---------- Exportar ----------


def test_exportar_trae_la_suscripcion_y_todos_los_pagos_de_la_cuenta(client, db, wompi) -> None:
    token, user_id, _, _ = _suscriptor_automatico(client, db, wompi)
    ajeno, _, _ = _suscriptor_manual(client, db, wompi)

    datos = client.get("/auth/me/export", headers=auth(token)).json()
    assert (datos["subscription"]["status"], datos["subscription"]["renewal_mode"]) == (
        "active",
        "automatic",
    )
    assert datos["subscription"]["card_last4"] == "4242"
    [pago] = datos["payments"]
    assert (pago["status"], pago["amount_cents"], pago["currency"]) == ("approved", PRECIO, "COP")
    assert pago["id"] == str(_pagos(db, user_id)[0].id)
    # Ni la referencia del medio de pago ni la del pago: son del proveedor.
    assert "3000" not in str(datos["subscription"]) and "reference" not in pago

    otro = client.get("/auth/me/export", headers=auth(ajeno)).json()
    assert otro["subscription"]["renewal_mode"] == "manual"
    assert [p["id"] for p in otro["payments"]] != [pago["id"]]
