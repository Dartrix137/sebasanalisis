"""Renovacion automatica (§3.5, §3.6, §3.8 y §3.9 de la Fase 4; paso 5.3b de la Fase 5).

El alta va por la API: el cliente paga el primer periodo en la pagina de la
pasarela y la tarjeta queda guardada alli. El job de renovaciones se llama
directo (`core/renewals.run_renewals`) con el `now` que cada test necesita: el
tiempo no se espera, se pasa. La pasarela es la simulada
(`pasarela_simulada.py`); las suscripciones de Tipster Page, con su proveedor
de verdad, estan en `test_tipster_suscripciones.py`.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select, text

from app.billing.periods import add_interval
from app.core.email import EmailMessage, FakeEmailSender
from app.core.renewals import advisory_lock, renewal_reference, run_renewals
from app.models import Payment, Plan, Subscription
from tests.api.conftest import auth
from tests.api.pasarela_simulada import PasarelaSimulada as Pasarela
from tests.api.test_billing import _cupon, _mensual
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


@pytest.fixture(autouse=True)
def sin_suscripciones_de_otros_tests(db) -> None:
    """El job recorre TODAS las suscripciones de la base, y la base de test es
    una sola para toda la corrida: cada test empieza sin las de los demas."""
    for tabla in ("invoices", "payment_events", "payments", "coupon_redemptions", "subscriptions"):
        db.execute(text(f"DELETE FROM {tabla}"))
    db.commit()


# ---------- Ayudas ----------


def _alta_automatica(client, token: str, plan_id, *, codigo=None, **cambios):
    """Abre el alta de la renovacion automatica: responde la pagina de la
    pasarela donde se paga el primer periodo (paso 5.3b)."""
    body = {
        "plan_id": str(plan_id),
        "renewal_mode": "automatic",
        "country": "CO",
        **cambios,
    }
    if codigo is not None:
        body["coupon_code"] = codigo
    return client.post("/billing/subscriptions", json=body, headers=auth(token))


def _pagar_alta(client, token: str, pasarela: Pasarela, respuesta, outcome: str = "approved") -> dict:
    """El cliente paga en la pagina de la pasarela y vuelve: la pantalla del
    pago reconsulta. Devuelve el pago como lo ve el cliente."""
    assert respuesta.status_code == 202, respuesta.text
    data = respuesta.json()
    pasarela.completar_alta(data["checkout_url"], outcome)
    r = client.get(f"/billing/payments/{data['payment_id']}", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _suscriptor_automatico(client, db, pasarela: Pasarela, *, codigo=None) -> tuple[str, str, str, Subscription]:
    """Una cuenta con el primer cobro aprobado y la renovacion automatica encendida."""
    token, user_id, correo = _cuenta(client, db)
    r = _alta_automatica(client, token, _mensual(db).id, codigo=codigo)
    assert _pagar_alta(client, token, pasarela, r)["status"] == "approved"
    db.expire_all()
    [suscripcion] = _suscripciones(db, user_id)
    assert suscripcion.status == "active", suscripcion.status
    return token, user_id, correo, suscripcion


def _correr(db, pasarela: Pasarela, cuando: datetime, sender=None):
    reporte = run_renewals(db, pasarela.provider, sender or FakeEmailSender(), cuando)
    db.expire_all()
    return reporte


def _correos(reporte) -> list:
    """Los avisos que salieron en la corrida y los correos que quedan por enviar."""
    return [*reporte.sent, *reporte.emails]


def _suscripcion(db, user_id: str) -> Subscription:
    [suscripcion] = _suscripciones(db, user_id)
    return suscripcion


def _de(reporte, correo: str) -> list[str]:
    return [m.subject for m in _correos(reporte) if m.to == correo]


# ---------- Disponibilidad y contratos ----------


def test_disponibilidad_dice_si_hay_renovacion_automatica(client, pasarela) -> None:
    assert client.get("/billing/availability").json() == {
        "enabled": True,
        "automatic_renewal": True,
    }


def test_sin_pasarela_no_se_ofrece_la_renovacion_automatica(client, db) -> None:
    assert client.get("/billing/availability").json() == {
        "enabled": False,
        "automatic_renewal": False,
    }


def test_los_contratos_y_la_llave_de_cifrado_de_wompi_ya_no_existen(client, db, pasarela) -> None:
    """La llave del formulario de tarjeta propio (§3.16) salio en el paso 5.1 y
    los dos contratos del procesador en el 5.3 de la Fase 5: eran de Wompi."""
    token, _, _ = _cuenta(client, db)
    rutas = client.get("/openapi.json").json()["paths"]
    for ruta in ("/billing/card-encryption-key", "/billing/acceptance"):
        assert client.get(ruta, headers=auth(token)).status_code == 404
        assert ruta not in rutas


# ---------- Alta: el primer periodo se paga en la pagina de la pasarela (paso 5.3b) ----------


def test_alta_automatica_abre_la_pagina_y_al_pagar_guarda_la_tarjeta(
    client, db, pasarela, outbox
) -> None:
    token, user_id, correo = _cuenta(client, db)
    outbox.clear()
    r = _alta_automatica(client, token, _mensual(db).id)
    assert r.status_code == 202, r.text
    data = r.json()
    assert data["checkout_url"].startswith("http://testserver/dev/fake-checkout/subscription/")
    assert (data["total_cents"], data["currency"]) == (PRECIO, "EUR")

    # A la pasarela se le abrio el alta con el monto del servidor, el pais y
    # la referencia del pago; todavia no se cobro nada.
    [alta] = pasarela.altas
    [pago] = _pagos(db, user_id)
    assert (alta.reference, alta.amount_cents, alta.currency) == (pago.reference, PRECIO, "EUR")
    assert (alta.country, alta.email, alta.interval, alta.interval_count) == ("CO", correo, "month", 1)
    assert alta.notification_url.endswith("/webhooks/payments")
    assert alta.url_ok.endswith(f"/pago/{pago.id}")
    assert (pago.status, pago.kind) == ("pending", "initial")
    assert pasarela.cobros == []
    suscripcion = _suscripcion(db, user_id)
    assert (suscripcion.status, suscripcion.renewal_mode, suscripcion.payment_source_id) == (
        "pending",
        "automatic",
        None,
    )
    assert not _tiene_acceso(client, token)

    # El cliente paga en la pagina y vuelve: la reconsulta aprueba el pago y
    # guarda la tarjeta que quedo en la pasarela.
    pasarela.completar_alta(data["checkout_url"])
    assert client.get(f"/billing/payments/{pago.id}", headers=auth(token)).json()["status"] == (
        "approved"
    )
    suscripcion = _suscripcion(db, user_id)
    assert (suscripcion.status, suscripcion.renewal_mode) == ("active", "automatic")
    # Solo la referencia de la pasarela, la marca y los ultimos cuatro.
    assert (
        suscripcion.payment_source_id,
        suscripcion.payment_source_type,
        suscripcion.provider_subscription_id,
        suscripcion.card_brand,
        suscripcion.card_last4,
    ) == ("3000", "CARD", f"fake-agreement-{data['checkout_url'].rsplit('/', 1)[1]}", "VISA", "4242")
    assert suscripcion.next_charge_at == suscripcion.current_period_end - 48 * H
    assert _tiene_acceso(client, token)

    assert _asuntos(outbox, correo) == [
        "Tu suscripción a Sebasanálisis está activa",
        "Recibo de tu pago en Sebasanálisis",
    ]
    bienvenida = next(m for m in outbox if "activa" in m.subject).text
    assert "Tu plan se renueva solo" in bienvenida and "antes de cada cobro te avisamos" in bienvenida

    visto = client.get("/billing/subscription", headers=auth(token)).json()
    assert (visto["renewal_mode"], visto["payment_source_type"], visto["card_last4"]) == (
        "automatic",
        "CARD",
        "4242",
    )
    assert visto["next_charge_at"] is not None and visto["next_charge_cents"] == PRECIO


def test_el_alta_la_puede_resolver_el_aviso_de_la_pasarela(client, db, pasarela) -> None:
    token, user_id, _ = _cuenta(client, db)
    r = _alta_automatica(client, token, _mensual(db).id)
    assert r.status_code == 202, r.text
    [pago] = _pagos(db, user_id)
    pasarela.completar_alta(r.json()["checkout_url"])

    # El cliente cerro la pestana: lo resuelve el aviso, con la reconsulta.
    assert _webhook(client, pasarela.evento(pago.provider_transaction_id)).status_code == 200
    assert _suscripcion(db, user_id).status == "active"
    assert _tiene_acceso(client, token)


def test_primer_pago_rechazado_no_da_acceso_y_se_puede_reintentar(client, db, pasarela, outbox) -> None:
    token, user_id, _ = _cuenta(client, db)
    outbox.clear()
    r = _alta_automatica(client, token, _mensual(db).id)
    assert _pagar_alta(client, token, pasarela, r, "declined")["status"] == "declined"
    suscripcion = _suscripcion(db, user_id)
    assert (suscripcion.status, suscripcion.payment_source_id) == ("pending", None)
    assert not _tiene_acceso(client, token)
    # No es una renovacion: no se manda el correo de cobro fallido.
    assert outbox == []

    r = _alta_automatica(client, token, _mensual(db).id)
    assert _pagar_alta(client, token, pasarela, r)["status"] == "approved"
    assert _suscripcion(db, user_id).status == "active"


def test_la_renovacion_automatica_exige_el_pais(client, db, pasarela) -> None:
    token, user_id, _ = _cuenta(client, db)
    r = _alta_automatica(client, token, _mensual(db).id, country=None)
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "country_required")
    assert _pagos(db, user_id) == [] and pasarela.altas == []


def test_sin_el_medio_de_la_pasarela_no_hay_alta_automatica(client, db, pasarela, monkeypatch) -> None:
    token, user_id, _ = _cuenta(client, db)
    monkeypatch.setattr(pasarela, "recurring_method", lambda country: None)
    r = _alta_automatica(client, token, _mensual(db).id)
    assert (r.status_code, r.json()["detail"]["code"]) == (503, "automatic_unavailable")
    assert _pagos(db, user_id) == [] and pasarela.altas == []


def test_un_monto_del_cliente_tampoco_cuenta_en_el_alta_automatica(client, db, pasarela) -> None:
    token, _, _ = _cuenta(client, db)
    r = _alta_automatica(client, token, _mensual(db).id, amount_cents=1, total_cents=1)
    assert r.status_code == 202
    assert pasarela.altas[0].amount_cents == PRECIO


def test_el_alta_automatica_lleva_el_descuento_del_cupon(client, db, pasarela) -> None:
    token, _, _ = _cuenta(client, db)
    cupon = _cupon(db, value=50)
    r = _alta_automatica(client, token, _mensual(db).id, codigo=cupon.code)
    assert r.status_code == 202, r.text
    assert pasarela.altas[0].amount_cents == PRECIO // 2


def test_si_pasarela_no_crea_el_alta_se_dice_y_no_queda_nada_abierto(client, db, pasarela) -> None:
    token, user_id, _ = _cuenta(client, db)
    pasarela.alta_caida = True
    r = _alta_automatica(client, token, _mensual(db).id)
    assert (r.status_code, r.json()["detail"]["code"]) == (502, "provider_unavailable")
    [pago] = _pagos(db, user_id)
    assert (pago.status, pago.provider_transaction_id) == ("error", None)
    assert not _tiene_acceso(client, token)

    pasarela.alta_caida = False
    r = _alta_automatica(client, token, _mensual(db).id)
    assert _pagar_alta(client, token, pasarela, r)["status"] == "approved"
    assert _tiene_acceso(client, token)


def test_con_renovacion_automatica_vigente_no_se_paga_a_mano(client, db, pasarela) -> None:
    token, _, _, _ = _suscriptor_automatico(client, db, pasarela)
    r = client.post(
        "/billing/subscriptions", json={"plan_id": str(_mensual(db).id)}, headers=auth(token)
    )
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "renews_automatically")


# ---------- Job: aviso antes del cobro ----------


def test_el_aviso_sale_siete_dias_antes_del_primer_intento_y_una_sola_vez(client, db, pasarela) -> None:
    """§3.8: antes del cobro, uno por periodo."""
    _, user_id, correo, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = suscripcion.current_period_end
    primer_intento = vence - 48 * H

    reporte = _correr(db, pasarela, primer_intento - 7 * DIA - H)
    assert (reporte.notices, _correos(reporte)) == (0, [])

    reporte = _correr(db, pasarela, primer_intento - 7 * DIA)
    assert reporte.notices == 1
    [aviso] = [m for m in _correos(reporte) if m.to == correo]
    assert aviso.subject == "Aviso: próximo cobro de tu suscripción a Sebasanálisis"
    # Que plan, cuanto, en que moneda, a que medio y como gestionarlo.
    assert "Acceso Mensual" in aviso.text and "32 EUR" in aviso.text
    assert "tu tarjeta Visa terminada en 4242" in aviso.text
    assert "/cuenta" in aviso.text and "cancela la renovación" in aviso.text

    # Las corridas siguientes no lo repiten.
    for horas in (1, 24, 100):
        assert _correr(db, pasarela, primer_intento - 7 * DIA + horas * H).notices == 0
    assert len(pasarela.cobros) == 1  # solo el del alta: todavia no toca cobrar


def test_si_el_aviso_no_ha_salido_la_corrida_avisa_y_no_cobra(client, db, pasarela) -> None:
    """El aviso va antes del cobro aunque el job haya estado caido."""
    _, user_id, correo, suscripcion = _suscriptor_automatico(client, db, pasarela)
    cuando = suscripcion.current_period_end - 40 * H  # ya paso la hora del primer intento

    reporte = _correr(db, pasarela, cuando)
    assert (reporte.notices, reporte.charges) == (1, 0)
    assert len(pasarela.cobros) == 1

    reporte = _correr(db, pasarela, cuando + H)
    assert (reporte.notices, reporte.charges, reporte.approved) == (0, 1, 1)


class _CorreoCaido:
    """Un servidor de correo que no responde."""

    def send(self, message: EmailMessage) -> None:
        raise ConnectionError("sin correo")


def test_si_el_aviso_no_sale_no_se_anota_ni_se_cobra_y_la_siguiente_corrida_avisa(
    client, db, pasarela
) -> None:
    """Un aviso que no llego no cuenta: sin aviso no hay cobro (2026-10-21)."""
    _, user_id, correo, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = suscripcion.current_period_end

    reporte = _correr(db, pasarela, vence - 9 * DIA, _CorreoCaido())
    assert (reporte.notices, reporte.notices_failed, _correos(reporte)) == (0, 1, [])
    assert _suscripcion(db, user_id).notice_sent_for is None

    # Llega la hora del primer intento con el correo todavia caido: no se cobra.
    reporte = _correr(db, pasarela, vence - 48 * H, _CorreoCaido())
    assert (reporte.notices_failed, reporte.charges) == (1, 0)
    assert len(pasarela.cobros) == 1  # solo el del alta

    # Vuelve el correo: esta corrida avisa y no cobra; la siguiente cobra.
    sender = FakeEmailSender()
    reporte = _correr(db, pasarela, vence - 47 * H, sender)
    assert (reporte.notices, reporte.notices_failed, reporte.charges) == (1, 0, 0)
    assert [m.to for m in sender.sent] == [correo]
    assert _suscripcion(db, user_id).notice_sent_for == vence

    reporte = _correr(db, pasarela, vence - 46 * H)
    assert (reporte.notices, reporte.charges, reporte.approved) == (0, 1, 1)


# ---------- Job: el cobro ----------


def _avisada(db, pasarela: Pasarela, suscripcion: Subscription) -> datetime:
    """Deja enviado el aviso del periodo y devuelve cuando vence."""
    vence = suscripcion.current_period_end
    assert _correr(db, pasarela, vence - 9 * DIA).notices == 1
    return vence


def test_la_renovacion_cobra_a_las_48_horas_y_extiende_desde_el_vencimiento(
    client, db, pasarela
) -> None:
    token, user_id, correo, suscripcion = _suscriptor_automatico(client, db, pasarela)
    inicio = suscripcion.current_period_start
    vence = _avisada(db, pasarela, suscripcion)

    # Antes de las 48 h no se cobra.
    assert _correr(db, pasarela, vence - 49 * H).charges == 0
    assert len(pasarela.cobros) == 1

    reporte = _correr(db, pasarela, vence - 48 * H)
    assert (reporte.charges, reporte.approved, reporte.failed) == (1, 1, 0)
    cobro = pasarela.cobros[1]
    assert cobro["reference"] == renewal_reference(suscripcion, vence, 1)
    assert cobro["reference"].startswith(f"SA-R-{suscripcion.id.hex}-")
    assert (cobro["amount_cents"], cobro["source_id"]) == (PRECIO, "3000")

    suscripcion = _suscripcion(db, user_id)
    # El periodo avanza desde el vencimiento anterior, no desde el dia del cobro.
    assert suscripcion.current_period_end == add_interval(vence, "month", 1)
    assert suscripcion.current_period_start == inicio
    assert (suscripcion.status, suscripcion.retry_count) == ("active", 0)
    assert suscripcion.next_charge_at == suscripcion.current_period_end - 48 * H
    renovacion = _pagos(db, user_id)[1]
    assert (renovacion.kind, renovacion.status) == ("renewal", "approved")
    assert (renovacion.period_start, renovacion.period_end) == (vence, add_interval(vence, "month", 1))
    # Recibo, sin bienvenida.
    assert _de(reporte, correo) == ["Recibo de tu pago en Sebasanálisis"]


def test_dos_corridas_sobre_el_mismo_periodo_un_solo_cobro(client, db, pasarela) -> None:
    """§3.9."""
    _, user_id, _, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = _avisada(db, pasarela, suscripcion)

    assert _correr(db, pasarela, vence - 48 * H).charges == 1
    for _ in range(3):
        reporte = _correr(db, pasarela, vence - 48 * H)
        assert (reporte.charges, _correos(reporte)) == (0, [])
    assert len(pasarela.cobros) == 2  # el del alta y uno de renovacion
    assert len(_pagos(db, user_id)) == 2


def test_un_intento_que_otra_corrida_ya_creo_no_se_cobra_dos_veces(client, db, pasarela) -> None:
    """La segunda capa: la referencia unica. Aqui el intento ya existe en la
    base, como si otra corrida lo hubiera creado y estuviera por cobrarlo."""
    _, user_id, _, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = _avisada(db, pasarela, suscripcion)
    cuando = vence - 48 * H
    db.add(
        Payment(
            subscription_id=suscripcion.id,
            user_id=uuid.UUID(user_id),
            plan_id=suscripcion.plan_id,
            provider="fake",
            reference=renewal_reference(suscripcion, vence, 1),
            kind="renewal",
            amount_cents=PRECIO,
            currency="EUR",
            status="pending",
            created_at=cuando,
        )
    )
    db.commit()

    reporte = _correr(db, pasarela, cuando)
    assert reporte.charges == 0
    assert len(pasarela.cobros) == 1
    # Y la restriccion de la base es la que lo garantiza.
    db.add(
        Payment(
            user_id=uuid.UUID(user_id),
            plan_id=suscripcion.plan_id,
            provider="fake",
            reference=renewal_reference(suscripcion, vence, 1),
            kind="renewal",
            amount_cents=PRECIO,
            currency="EUR",
            status="pending",
        )
    )
    with pytest.raises(Exception, match="payments_reference_key"):
        db.commit()
    db.rollback()


def test_el_candado_del_job_no_deja_dos_corridas_a_la_vez(test_database) -> None:
    engine = create_engine(test_database)
    with advisory_lock(engine) as primera:
        assert primera is True
        with advisory_lock(engine) as segunda:
            assert segunda is False
    # Al terminar la primera, el candado queda libre.
    with advisory_lock(engine) as tercera:
        assert tercera is True
    engine.dispose()


def test_un_cobro_que_quedo_pendiente_se_reconsulta_y_no_se_repite(client, db, pasarela) -> None:
    _, user_id, _, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = _avisada(db, pasarela, suscripcion)

    pasarela.estado_del_cobro = "PENDING"
    reporte = _correr(db, pasarela, vence - 48 * H)
    assert (reporte.charges, reporte.approved, reporte.failed) == (1, 0, 0)
    renovacion = _pagos(db, user_id)[1]
    assert renovacion.status == "pending"

    # Mientras siga pendiente no se hace otro intento, ni siquiera a las 24 h.
    assert _correr(db, pasarela, vence - 24 * H).charges == 0
    assert len(pasarela.cobros) == 2

    pasarela.resolver(renovacion.provider_transaction_id, "APPROVED")
    reporte = _correr(db, pasarela, vence - 23 * H)
    assert (reporte.charges, reporte.approved) == (0, 1)
    assert _suscripcion(db, user_id).current_period_end == add_interval(vence, "month", 1)


# ---------- Job: cobros fallidos y vencimiento ----------


def test_los_tres_intentos_fallan_y_vence_exactamente_en_el_vencimiento(client, db, pasarela) -> None:
    """§3.9: acceso hasta `current_period_end`; estado `expired`."""
    token, user_id, correo, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = _avisada(db, pasarela, suscripcion)
    pasarela.estado_del_cobro = "DECLINED"

    # 48 h antes: primer intento, rechazado.
    reporte = _correr(db, pasarela, vence - 48 * H)
    assert (reporte.charges, reporte.failed, reporte.expired) == (1, 1, 0)
    suscripcion = _suscripcion(db, user_id)
    assert (suscripcion.status, suscripcion.retry_count) == ("past_due", 1)
    assert suscripcion.current_period_end == vence  # el periodo no se mueve
    # En mora conserva el acceso: el periodo pagado sigue corriendo.
    assert _tiene_acceso(client, token)
    [fallido] = [m for m in _correos(reporte) if m.to == correo]
    assert fallido.subject == "No pudimos cobrar la renovación de tu suscripción a Sebasanálisis"
    assert "32 EUR" in fallido.text and "conservas el acceso" in fallido.text

    # Entre intentos no se cobra.
    assert _correr(db, pasarela, vence - 30 * H).charges == 0

    # 24 h antes: segundo intento.
    reporte = _correr(db, pasarela, vence - 24 * H)
    assert (reporte.charges, reporte.failed, reporte.expired) == (1, 1, 0)
    assert _suscripcion(db, user_id).retry_count == 2

    # Justo antes del vencimiento todavia no vence ni se hace el tercero.
    reporte = _correr(db, pasarela, vence - timedelta(minutes=1))
    assert (reporte.charges, reporte.expired) == (0, 0)
    assert _suscripcion(db, user_id).status == "past_due"

    # En el vencimiento: tercer intento, rechazado, y vence. Sin gracia.
    reporte = _correr(db, pasarela, vence)
    assert (reporte.charges, reporte.failed, reporte.expired) == (1, 1, 1)
    suscripcion = _suscripcion(db, user_id)
    assert (suscripcion.status, suscripcion.current_period_end, suscripcion.next_charge_at) == (
        "expired",
        vence,
        None,
    )
    assert _de(reporte, correo) == [
        "No pudimos cobrar la renovación de tu suscripción a Sebasanálisis",
        "Tu suscripción a Sebasanálisis venció",
    ]
    vencida = _correos(reporte)[-1].text
    assert "tres veces" in vencida and "No vamos a intentarlo más" in vencida

    # Tres intentos, ni uno mas, con sus tres referencias.
    renovaciones = [p for p in _pagos(db, user_id) if p.kind == "renewal"]
    assert sorted(p.reference for p in renovaciones) == [
        renewal_reference(suscripcion, vence, n) for n in (1, 2, 3)
    ]
    assert {p.status for p in renovaciones} == {"declined"}
    for horas in (1, 24, 500):
        reporte = _correr(db, pasarela, vence + horas * H)
        assert (reporte.charges, reporte.expired, _correos(reporte)) == (0, 0, [])
    assert len(pasarela.cobros) == 4  # el del alta y los tres intentos

    # El acceso quedo revocado: el periodo termino y nada lo extendio.
    db.execute(
        text("UPDATE subscriptions SET current_period_end = :e WHERE user_id = :u"),
        {"e": datetime.now(UTC) - timedelta(minutes=1), "u": user_id},
    )
    db.commit()
    r = client.get("/sessions", headers=auth(token))
    assert (r.status_code, r.json()["detail"]["code"]) == (403, "expired")


def test_un_intento_falla_y_el_siguiente_pasa(client, db, pasarela) -> None:
    token, user_id, correo, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = _avisada(db, pasarela, suscripcion)

    pasarela.estado_del_cobro = "DECLINED"
    assert _correr(db, pasarela, vence - 48 * H).failed == 1
    assert _suscripcion(db, user_id).status == "past_due"

    pasarela.estado_del_cobro = "APPROVED"
    reporte = _correr(db, pasarela, vence - 24 * H)
    assert (reporte.charges, reporte.approved) == (1, 1)
    suscripcion = _suscripcion(db, user_id)
    assert (suscripcion.status, suscripcion.retry_count) == ("active", 0)
    assert suscripcion.current_period_end == add_interval(vence, "month", 1)
    assert pasarela.cobros[-1]["reference"].endswith("-2")
    assert _de(reporte, correo) == ["Recibo de tu pago en Sebasanálisis"]


def test_si_pasarela_no_responde_cuenta_como_intento_y_no_se_le_escribe_al_cliente(
    client, db, pasarela
) -> None:
    _, user_id, correo, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = _avisada(db, pasarela, suscripcion)
    pasarela.cobro_caido = True
    reporte = _correr(db, pasarela, vence - 48 * H)
    assert (reporte.charges, reporte.failed, _correos(reporte)) == (1, 1, [])
    assert _suscripcion(db, user_id).status == "past_due"
    renovacion = _pagos(db, user_id)[1]
    assert (renovacion.status, renovacion.provider_transaction_id) == ("error", None)

    pasarela.cobro_caido = False
    assert _correr(db, pasarela, vence - 24 * H).approved == 1


def test_el_cambio_de_precio_del_plan_no_toca_la_renovacion(client, db, pasarela) -> None:
    """§3.9: las suscripciones vigentes renuevan con su precio congelado."""
    _, user_id, _, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = _avisada(db, pasarela, suscripcion)
    db.execute(text("UPDATE plans SET price_cents = 4000 WHERE code = 'mensual'"))
    db.commit()
    try:
        assert _correr(db, pasarela, vence - 48 * H).approved == 1
    finally:
        db.execute(text("UPDATE plans SET price_cents = 3200 WHERE code = 'mensual'"))
        db.commit()
    assert pasarela.cobros[-1]["amount_cents"] == PRECIO
    assert _suscripcion(db, user_id).price_cents == PRECIO


def test_cupon_repeating_descuenta_un_periodo_en_cada_renovacion(client, db, pasarela) -> None:
    """Tres periodos con 20 %: el alta y dos renovaciones; la tercera, completa."""
    cupon = _cupon(db, value=20, duration="repeating", duration_periods=3)
    _, user_id, correo, suscripcion = _suscriptor_automatico(client, db, pasarela, codigo=cupon.code)
    assert pasarela.cobros[0]["amount_cents"] == 2_560
    assert (suscripcion.price_cents, suscripcion.discount_periods_remaining) == (PRECIO, 2)

    esperados = [(2_560, 1), (2_560, 0), (PRECIO, 0)]
    for monto, quedan in esperados:
        suscripcion = _suscripcion(db, user_id)
        vence = suscripcion.current_period_end
        aviso = _correr(db, pasarela, vence - 9 * DIA)
        # El aviso anuncia lo que de verdad se va a cobrar.
        esperado = "25,60 EUR" if monto == 2_560 else "32 EUR"
        assert esperado in _correos(aviso)[0].text
        assert _correr(db, pasarela, vence - 48 * H).approved == 1
        assert pasarela.cobros[-1]["amount_cents"] == monto
        assert _suscripcion(db, user_id).discount_periods_remaining == quedan

    db.refresh(cupon)
    assert cupon.redemptions_count == 1  # una redencion, no una por periodo


def test_el_pago_manual_del_siguiente_periodo_tambien_lleva_el_descuento(client, db, pasarela) -> None:
    cupon = _cupon(db, value=20, duration="forever")
    token, user_id, _ = _cuenta(client, db)
    _aprobar(client, pasarela, _abrir_pago(client, db, token, codigo=cupon.code))
    siguiente = _abrir_pago(client, db, token)
    assert (siguiente.kind, siguiente.amount_cents, siguiente.discount_cents) == (
        "renewal",
        2_560,
        640,
    )


# ---------- Cancelar y reanudar ----------


def test_cancelar_conserva_el_acceso_y_detiene_los_cobros(client, db, pasarela, outbox) -> None:
    """§3.9: acceso hasta `current_period_end`, sin cobros despues."""
    token, user_id, correo, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = suscripcion.current_period_end
    outbox.clear()

    assert client.post("/billing/subscription/cancel").status_code == 401
    r = client.post("/billing/subscription/cancel", headers=auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert (data["status"], data["cancel_at_period_end"], data["in_force"]) == ("canceled", True, True)
    assert (data["next_charge_at"], data["next_charge_cents"]) == (None, None)
    assert _tiene_acceso(client, token)
    assert _asuntos(outbox, correo) == ["Cancelaste la renovación de tu suscripción a Sebasanálisis"]
    assert "No te vamos\na hacer más cobros" in outbox[0].text.replace("  ", " ") or "más cobros" in outbox[0].text

    # Cancelar dos veces no hace nada.
    r = client.post("/billing/subscription/cancel", headers=auth(token))
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "nothing_to_cancel")

    # El job no avisa ni cobra.
    for cuando in (vence - 9 * DIA, vence - 48 * H, vence - 24 * H, vence - H):
        reporte = _correr(db, pasarela, cuando)
        assert (reporte.notices, reporte.charges, _correos(reporte)) == (0, 0, [])
    assert len(pasarela.cobros) == 1
    assert _suscripcion(db, user_id).current_period_end == vence

    # Al terminar el periodo queda vencida, sin correo: ya sabia.
    reporte = _correr(db, pasarela, vence)
    assert (reporte.expired, reporte.charges, _correos(reporte)) == (1, 0, [])
    assert _suscripcion(db, user_id).status == "expired"


def test_reanudar_antes_del_vencimiento_vuelve_a_cobrar(client, db, pasarela) -> None:
    token, user_id, _, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = suscripcion.current_period_end
    assert client.post("/billing/subscription/cancel", headers=auth(token)).status_code == 200

    r = client.post("/billing/subscription/resume", headers=auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert (data["status"], data["cancel_at_period_end"]) == ("active", False)
    assert data["next_charge_at"] is not None
    suscripcion = _suscripcion(db, user_id)
    assert suscripcion.next_charge_at == vence - 48 * H and suscripcion.canceled_at is None

    r = client.post("/billing/subscription/resume", headers=auth(token))
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "nothing_to_resume")

    assert _correr(db, pasarela, vence - 9 * DIA).notices == 1
    assert _correr(db, pasarela, vence - 48 * H).approved == 1


def test_reanudar_quita_un_pago_que_se_abrio_despues_de_cancelar(client, db, pasarela) -> None:
    """Cancelo, abrio un pago manual que no completo, y se arrepiente."""
    token, user_id, _, _ = _suscriptor_automatico(client, db, pasarela)
    client.post("/billing/subscription/cancel", headers=auth(token))
    _abrir_pago(client, db, token)
    assert sorted(s.status for s in _suscripciones(db, user_id)) == ["canceled", "pending"]

    assert client.post("/billing/subscription/resume", headers=auth(token)).status_code == 200
    assert [s.status for s in _suscripciones(db, user_id)] == ["active"]


def test_un_cobro_en_curso_al_cancelar_se_respeta_sin_reactivar_la_renovacion(
    client, db, pasarela
) -> None:
    token, user_id, _, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = _avisada(db, pasarela, suscripcion)
    pasarela.estado_del_cobro = "PENDING"
    _correr(db, pasarela, vence - 48 * H)
    renovacion = _pagos(db, user_id)[1]

    assert client.post("/billing/subscription/cancel", headers=auth(token)).status_code == 200
    pasarela.resolver(renovacion.provider_transaction_id, "APPROVED")
    assert _webhook(client, pasarela.evento(renovacion.provider_transaction_id)).status_code == 200

    suscripcion = _suscripcion(db, user_id)
    # Se le da el periodo que se cobro, pero sigue cancelada: no habra mas cobros.
    assert suscripcion.current_period_end == add_interval(vence, "month", 1)
    assert (suscripcion.status, suscripcion.cancel_at_period_end, suscripcion.next_charge_at) == (
        "canceled",
        True,
        None,
    )


def test_no_hay_nada_que_cancelar_sin_suscripcion_o_con_pago_manual(client, db, pasarela) -> None:
    token, _, _ = _cuenta(client, db)
    r = client.post("/billing/subscription/cancel", headers=auth(token))
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "nothing_to_cancel")

    _aprobar(client, pasarela, _abrir_pago(client, db, token))
    r = client.post("/billing/subscription/cancel", headers=auth(token))
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "not_automatic")
    assert _tiene_acceso(client, token)


# ---------- Job: pago manual ----------


def test_pago_manual_aviso_de_vencimiento_y_vencimiento_sin_ningun_cobro(client, db, pasarela) -> None:
    token, user_id, correo = _cuenta(client, db)
    _aprobar(client, pasarela, _abrir_pago(client, db, token))
    suscripcion = _suscripcion(db, user_id)
    vence = suscripcion.current_period_end

    assert _correos(_correr(db, pasarela, vence - 7 * DIA - H)) == []

    reporte = _correr(db, pasarela, vence - 7 * DIA)
    assert reporte.notices == 1
    [aviso] = [m for m in _correos(reporte) if m.to == correo]
    assert aviso.subject == "Tu acceso a Sebasanálisis está por terminar"
    assert "no te vamos a hacer ningún cobro" in aviso.text and "32 EUR" in aviso.text
    assert f"/planes/pagar?plan={suscripcion.plan_id}" in aviso.text
    # Una vez por periodo.
    assert _correos(_correr(db, pasarela, vence - 3 * DIA)) == []

    reporte = _correr(db, pasarela, vence)
    assert (reporte.expired, reporte.charges) == (1, 0)
    [vencida] = [m for m in _correos(reporte) if m.to == correo]
    assert vencida.subject == "Tu suscripción a Sebasanálisis venció"
    assert "pago manual" in vencida.text and "tres veces" not in vencida.text
    assert _suscripcion(db, user_id).status == "expired"
    # Nunca se le cobro nada por el job.
    assert pasarela.cobros == []
    assert _correos(_correr(db, pasarela, vence + DIA)) == []


def test_si_el_aviso_nunca_sale_la_suscripcion_vence_en_su_fecha_sin_cobrar(
    client, db, pasarela
) -> None:
    """Sin aviso no se cobra; pasado el vencimiento, vence (2026-10-21)."""
    token, user_id, correo, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = suscripcion.current_period_end

    assert _correr(db, pasarela, vence - 9 * DIA, _CorreoCaido()).notices_failed == 1
    reporte = _correr(db, pasarela, vence - H, _CorreoCaido())
    assert (reporte.notices_failed, reporte.expired) == (1, 0)
    assert _suscripcion(db, user_id).status == "active"

    reporte = _correr(db, pasarela, vence, _CorreoCaido())
    assert (reporte.notices_failed, reporte.expired, reporte.charges) == (1, 1, 0)
    assert _suscripcion(db, user_id).status == "expired"
    assert len(pasarela.cobros) == 1  # solo el del alta
    assert not _tiene_acceso(client, token)
    [vencida] = [m for m in _correos(reporte) if m.to == correo]
    assert "No pudimos enviarte el aviso del cobro" in vencida.text
    assert "tres veces" not in vencida.text

    # Ya vencida, el job no vuelve a intentar nada.
    reporte = _correr(db, pasarela, vence + H)
    assert (reporte.notices, reporte.notices_failed, reporte.charges, _correos(reporte)) == (0, 0, 0, [])


def test_un_aviso_que_sale_despues_del_vencimiento_todavia_cobra(client, db, pasarela) -> None:
    """El job estuvo caido hasta pasado el vencimiento: avisa, y la siguiente
    corrida cobra. Lo que vence es el aviso que no sale, no el que sale tarde."""
    _, user_id, _, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = suscripcion.current_period_end

    reporte = _correr(db, pasarela, vence + H)
    assert (reporte.notices, reporte.expired, reporte.charges) == (1, 0, 0)
    reporte = _correr(db, pasarela, vence + 2 * H)
    assert (reporte.charges, reporte.approved) == (1, 1)
    assert _suscripcion(db, user_id).status == "active"


def test_pago_manual_el_aviso_que_no_sale_se_reintenta_en_la_siguiente_corrida(
    client, db, pasarela
) -> None:
    token, user_id, correo = _cuenta(client, db)
    _aprobar(client, pasarela, _abrir_pago(client, db, token))
    vence = _suscripcion(db, user_id).current_period_end

    reporte = _correr(db, pasarela, vence - 7 * DIA, _CorreoCaido())
    assert (reporte.notices, reporte.notices_failed) == (0, 1)
    assert _suscripcion(db, user_id).notice_sent_for is None

    sender = FakeEmailSender()
    assert _correr(db, pasarela, vence - 7 * DIA + H, sender).notices == 1
    [aviso] = sender.sent
    assert (aviso.to, aviso.subject) == (correo, "Tu acceso a Sebasanálisis está por terminar")
    assert _correr(db, pasarela, vence - 3 * DIA).notices == 0


def test_pagar_a_mano_despues_del_aviso_renueva_y_vuelve_a_avisar_el_periodo_siguiente(
    client, db, pasarela
) -> None:
    token, user_id, correo = _cuenta(client, db)
    _aprobar(client, pasarela, _abrir_pago(client, db, token))
    vence = _suscripcion(db, user_id).current_period_end
    assert _correr(db, pasarela, vence - 7 * DIA).notices == 1

    _aprobar(client, pasarela, _abrir_pago(client, db, token))
    nuevo = _suscripcion(db, user_id).current_period_end
    assert nuevo == add_interval(vence, "month", 1)
    # El vencimiento viejo ya no vence nada.
    reporte = _correr(db, pasarela, vence + H)
    assert (reporte.expired, _correos(reporte)) == (0, [])
    assert _correr(db, pasarela, nuevo - 7 * DIA).notices == 1


def test_una_suscripcion_con_problemas_no_detiene_a_las_demas(client, db, pasarela) -> None:
    _, mala_id, _, mala = _suscriptor_automatico(client, db, pasarela)
    _, buena_id, _, buena = _suscriptor_automatico(client, db, pasarela)
    vence = max(mala.current_period_end, buena.current_period_end)
    _correr(db, pasarela, vence - 9 * DIA)
    # A la primera se le pierde el medio de pago; la segunda cobra normal.
    db.execute(
        text("UPDATE subscriptions SET payment_source_id = NULL WHERE user_id = :u"), {"u": mala_id}
    )
    db.commit()
    reporte = _correr(db, pasarela, vence - 47 * H)
    assert reporte.approved == 1
    assert _suscripcion(db, buena_id).current_period_end > vence


def test_el_plan_de_dos_meses_renueva_dos_meses(client, db, pasarela) -> None:
    token, user_id, _ = _cuenta(client, db)
    bimestral = db.scalar(select(Plan).where(Plan.code == "bimestral"))
    assert _pagar_alta(client, token, pasarela, _alta_automatica(client, token, bimestral.id))[
        "status"
    ] == "approved"
    suscripcion = _suscripcion(db, user_id)
    vence = _avisada(db, pasarela, suscripcion)
    assert _correr(db, pasarela, vence - 48 * H).approved == 1
    assert pasarela.cobros[-1]["amount_cents"] == 4_600
    assert _suscripcion(db, user_id).current_period_end == add_interval(vence, "month", 2)


# ---------- Cambio de tarjeta en la pagina de la pasarela (paso 5.3b) ----------


def test_cambiar_la_tarjeta_en_la_pagina_de_la_pasarela_simulada(client, db, pasarela) -> None:
    token, user_id, _, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vieja = suscripcion.payment_source_id
    r = client.post("/billing/payment-method/checkout", headers=auth(token))
    assert r.status_code == 200, r.text
    url = r.json()["checkout_url"]
    assert url.startswith("http://testserver/dev/fake-checkout/card/")

    ruta = url.removeprefix("http://testserver")
    assert client.get(ruta).status_code == 200
    r = client.post(ruta, data={"outcome": "approved"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/cuenta?tarjeta=guardada")

    r = client.post("/billing/payment-method/sync", headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["card_last4"] == "5454"
    [suscripcion] = _suscripciones(db, user_id)
    assert suscripcion.payment_source_id not in (None, vieja)
    # Ese enlace ya se uso.
    assert client.get(ruta).status_code == 404
