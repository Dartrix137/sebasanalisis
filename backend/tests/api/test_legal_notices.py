"""Aviso por correo de una version nueva de un documento legal (paso 9, §6.7).

`send_legal_notices` se llama directo, como el job, con un `FakeEmailSender`.
La base de test se comparte entre modulos: otros tests ya publicaron versiones
y crearon suscripciones, asi que cada test mira solo los correos de sus cuentas
y pide tandas grandes (`limit`) para alcanzarlas.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.core.email import EmailMessage, FakeEmailSender
from app.core.legal_notices import (
    NOTICES_PER_RUN,
    PUBLIC_PATHS,
    _sent_today,
    batch_size,
    notifiable_documents,
    pending_for,
    send_legal_notices,
)
from app.models import LegalDocument, LegalNotice
from tests.api.conftest import auth
from tests.api.test_legal import _publish
from tests.api.test_renewals import _suscriptor_automatico
from tests.api.test_subscriptions import _cuenta

TODOS = 100_000
ASUNTO = "Actualizamos los documentos legales de Sebasanálisis"


def _avisar(db, sender=None, *, limit: int = TODOS, daily_limit: int = 0):
    reporte = send_legal_notices(
        db, sender or FakeEmailSender(), datetime.now(UTC), limit=limit, daily_limit=daily_limit
    )
    db.expire_all()
    return reporte


def _correos(sender: FakeEmailSender, correo: str) -> list[EmailMessage]:
    return [m for m in sender.sent if m.to == correo]


def _aceptar(client, token: str, document_id: str) -> None:
    r = client.post(
        "/legal/accept", json={"legal_document_ids": [document_id]}, headers=auth(token)
    )
    assert r.status_code == 200, r.text


def _avisos(db, user_id: str) -> list[LegalNotice]:
    return list(db.scalars(select(LegalNotice).where(LegalNotice.user_id == user_id)))


# ---------- Reglas puras ----------


def test_tamano_de_la_tanda() -> None:
    assert batch_size(40, 0, 10_000) == 40  # sin tope diario
    assert batch_size(40, 150, 0) == 40
    assert batch_size(40, 150, 140) == 10
    assert batch_size(40, 150, 150) == 0
    assert batch_size(40, 150, 999) == 0


def test_que_documentos_le_faltan_a_una_cuenta() -> None:
    terminos = LegalDocument(id=uuid.uuid4(), kind="terms", version=3, title="T", content_md="x")
    datos = LegalDocument(id=uuid.uuid4(), kind="privacy", version=2, title="D", content_md="x")
    # Acepto la 2 de terminos y la 2 de datos: le falta la 3 de terminos.
    assert pending_for([terminos, datos], {"terms": 2, "privacy": 2}, set()) == [terminos]
    # Ya se le aviso de esa version.
    assert pending_for([terminos, datos], {"terms": 2, "privacy": 2}, {terminos.id}) == []
    # Acepto una version igual o posterior.
    assert pending_for([terminos], {"terms": 3}, set()) == []


def test_solo_se_avisa_de_una_version_que_reemplaza_a_otra(client, admin_token: str, db) -> None:
    """La version 1 que publico la migracion no "cambia" nada: no se avisa. Una
    que no exige aceptacion (una errata) tampoco."""
    _publish(client, admin_token, "cookies", requires_acceptance=False)
    for doc in notifiable_documents(db):
        assert doc.requires_acceptance and doc.version > 1
        assert doc.kind != "cookies"


# ---------- A quien ----------


def test_una_version_nueva_le_llega_a_quien_tiene_suscripcion_vigente(
    client, db, pasarela, admin_token: str
) -> None:
    _, user_id, correo, _ = _suscriptor_automatico(client, db, pasarela)
    terminos = _publish(client, admin_token, "terms")

    sender = FakeEmailSender()
    _avisar(db, sender)
    [mensaje] = _correos(sender, correo)
    assert mensaje.subject == ASUNTO
    assert terminos["title"] in mensaje.text
    assert f"versión {terminos['version']}" in mensaje.text
    assert f"{PUBLIC_PATHS['terms']}" in mensaje.text
    assert "/cuenta" in mensaje.text
    # Se renueva sola: el correo dice como detener los cobros.
    assert "puedes cancelar la renovación" in mensaje.text
    assert "sin aceptarla no puedes usar la mesa" in mensaje.text
    [aviso] = _avisos(db, user_id)
    assert str(aviso.legal_document_id) == terminos["id"]


def test_no_le_llega_a_quien_no_tiene_suscripcion_ni_a_correos_sin_verificar(
    client, db, pasarela, admin_token: str
) -> None:
    _, _, sin_suscripcion = _cuenta(client, db)
    _, _, sin_verificar, _ = _suscriptor_automatico(client, db, pasarela)
    db.execute(text("UPDATE users SET email_verified = false WHERE email = :e"), {"e": sin_verificar})
    _, _, suspendida, _ = _suscriptor_automatico(client, db, pasarela)
    db.execute(text("UPDATE users SET is_active = false WHERE email = :e"), {"e": suspendida})
    _, _, vencida, sub = _suscriptor_automatico(client, db, pasarela)
    db.execute(
        text("UPDATE subscriptions SET current_period_end = now() - interval '1 day' WHERE id = :id"),
        {"id": sub.id},
    )
    _, _, cancelada, sub_cancelada = _suscriptor_automatico(client, db, pasarela)
    db.execute(
        text("UPDATE subscriptions SET status = 'canceled' WHERE id = :id"), {"id": sub_cancelada.id}
    )
    db.commit()
    _publish(client, admin_token, "privacy")

    sender = FakeEmailSender()
    _avisar(db, sender)
    for correo in (sin_suscripcion, sin_verificar, suspendida, vencida):
        assert _correos(sender, correo) == [], correo
    # Cancelada con el periodo vigente: si, y sin el parrafo de la renovacion.
    [mensaje] = _correos(sender, cancelada)
    assert "puedes cancelar la renovación" not in mensaje.text


def test_no_le_llega_a_quien_ya_acepto_la_version_nueva(client, db, pasarela, admin_token: str) -> None:
    token, _, correo, _ = _suscriptor_automatico(client, db, pasarela)
    terminos = _publish(client, admin_token, "terms")
    _aceptar(client, token, terminos["id"])

    sender = FakeEmailSender()
    _avisar(db, sender)
    assert _correos(sender, correo) == []


# ---------- Idempotencia y tandas ----------


def test_si_el_job_corre_dos_veces_nadie_recibe_el_aviso_dos_veces(
    client, db, pasarela, admin_token: str
) -> None:
    _, _, correo, _ = _suscriptor_automatico(client, db, pasarela)
    _publish(client, admin_token, "terms")

    primera, segunda = FakeEmailSender(), FakeEmailSender()
    _avisar(db, primera)
    reporte = _avisar(db, segunda)
    assert len(_correos(primera, correo)) == 1
    assert _correos(segunda, correo) == []
    assert reporte.sent == 0


def test_terminos_y_datos_a_la_vez_van_en_un_solo_correo(client, db, pasarela, admin_token: str) -> None:
    _, user_id, correo, _ = _suscriptor_automatico(client, db, pasarela)
    terminos = _publish(client, admin_token, "terms")
    datos = _publish(client, admin_token, "privacy")

    sender = FakeEmailSender()
    _avisar(db, sender)
    [mensaje] = _correos(sender, correo)
    assert terminos["title"] in mensaje.text and datos["title"] in mensaje.text
    assert PUBLIC_PATHS["terms"] in mensaje.text and PUBLIC_PATHS["privacy"] in mensaje.text
    assert len(_avisos(db, user_id)) == 2

    # Otra version de los terminos despues: otro aviso, solo de los terminos.
    nuevos = _publish(client, admin_token, "terms")
    sender = FakeEmailSender()
    _avisar(db, sender)
    [mensaje] = _correos(sender, correo)
    assert f"versión {nuevos['version']}" in mensaje.text
    assert PUBLIC_PATHS["privacy"] not in mensaje.text


def test_dos_versiones_antes_del_aviso_dan_un_solo_correo_de_la_ultima(
    client, db, pasarela, admin_token: str
) -> None:
    _, _, correo, _ = _suscriptor_automatico(client, db, pasarela)
    _publish(client, admin_token, "terms")
    ultima = _publish(client, admin_token, "terms")

    sender = FakeEmailSender()
    _avisar(db, sender)
    [mensaje] = _correos(sender, correo)
    assert f"versión {ultima['version']}" in mensaje.text


def test_si_el_correo_no_sale_se_reintenta_en_la_siguiente_corrida(
    client, db, pasarela, admin_token: str
) -> None:
    _, user_id, correo, _ = _suscriptor_automatico(client, db, pasarela)
    _publish(client, admin_token, "terms")

    class Caido:
        def send(self, message: EmailMessage) -> None:
            raise ConnectionError("SMTP caido")

    reporte = _avisar(db, Caido())
    assert reporte.sent == 0 and reporte.failed > 0
    assert _avisos(db, user_id) == []

    sender = FakeEmailSender()
    _avisar(db, sender)
    assert len(_correos(sender, correo)) == 1


def test_los_avisos_salen_por_tandas_sin_repetir(client, db, pasarela, admin_token: str) -> None:
    for _ in range(3):
        _suscriptor_automatico(client, db, pasarela)
    _publish(client, admin_token, "terms")

    primera = _avisar(db, limit=2)
    assert primera.sent == 2
    resto = _avisar(db)
    assert resto.sent >= 1
    assert not set(primera.recipients) & set(resto.recipients)
    assert _avisar(db).sent == 0
    assert NOTICES_PER_RUN == 40


def test_el_tope_diario_se_cuenta_en_la_base(client, db, pasarela, admin_token: str) -> None:
    # Un aviso enviado hoy, para que el tope cuente algo.
    _suscriptor_automatico(client, db, pasarela)
    _publish(client, admin_token, "terms")
    _avisar(db)
    _, _, correo, _ = _suscriptor_automatico(client, db, pasarela)
    _publish(client, admin_token, "terms")
    ahora = datetime.now(UTC)
    ya_enviados = _sent_today(db, ahora)
    assert ya_enviados > 0

    sender = FakeEmailSender()
    reporte = send_legal_notices(db, sender, ahora, limit=TODOS, daily_limit=ya_enviados)
    assert reporte.sent == 0 and reporte.deferred_by_daily_limit
    assert _correos(sender, correo) == []

    # Al dia siguiente el tope se renueva.
    manana = ahora + timedelta(days=1)
    reporte = send_legal_notices(db, sender, manana, limit=TODOS, daily_limit=ya_enviados + TODOS)
    assert len(_correos(sender, correo)) == 1


def test_eliminar_la_cuenta_borra_sus_avisos(client, db, pasarela, admin_token: str) -> None:
    token, user_id, _, _ = _suscriptor_automatico(client, db, pasarela)
    _publish(client, admin_token, "terms")
    _avisar(db)
    assert _avisos(db, user_id)
    r = client.request(
        "DELETE", "/auth/me", json={"password": "clave-segura-123"}, headers=auth(token)
    )
    assert r.status_code == 204, r.text
    db.expire_all()
    assert _avisos(db, user_id) == []
