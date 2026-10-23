"""Resumen del admin y acciones sobre la cuenta (§4.2 y §4.7; paso 6, entrega 2).

Las suscripciones y los pagos salen del doble de la pasarela, como en
`test_admin_payments.py`. Las fechas de los pagos que caen en el mes anterior
se mueven a mano en la base.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.core.overview import periods
from app.models import AdminAuditLog, Plan
from tests.api.conftest import auth
from tests.api.test_admin_payments import (
    MOTIVO,
    _accion,
    _reembolso,
    _suscriptor_manual,
    sin_suscripciones_de_otros_tests,  # noqa: F401 - fixture autouse
)
from tests.api.test_renewals import _suscriptor_automatico
from tests.api.test_subscriptions import (
    PRECIO,
    _abrir_pago,
    _aprobar,
    _cuenta,
    _pagos,
    _webhook,
)


def _resumen(client, admin_token: str) -> dict:
    r = client.get("/admin/overview", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    return r.json()


def _filas(db, action: str, target_id) -> list[AdminAuditLog]:
    db.expire_all()
    return list(
        db.scalars(
            select(AdminAuditLog).where(
                AdminAuditLog.action == action, AdminAuditLog.target_id == str(target_id)
            )
        )
    )


# ---------- Resumen ----------


def test_el_resumen_es_solo_para_administradores(client, user_token: str) -> None:
    assert client.get("/admin/overview").status_code == 401
    assert client.get("/admin/overview", headers=auth(user_token)).status_code == 403


def test_el_resumen_dice_que_periodos_compara(client, admin_token: str) -> None:
    data = _resumen(client, admin_token)
    p = periods(datetime.now(UTC))
    periodo = data["period"]
    assert periodo["timezone"] == "America/Bogota"
    assert datetime.fromisoformat(periodo["current_start"]) == p.current.start
    assert datetime.fromisoformat(periodo["previous_start"]) == p.previous.start


def test_el_resumen_cuenta_suscripciones_recurrente_y_cobrado(
    client, db, pasarela, admin_token: str
) -> None:
    # Una manual mensual, una automatica mensual y una manual bimestral.
    _, _, _, manual = _suscriptor_manual(client, db, pasarela)
    _, _, _, automatica = _suscriptor_automatico(client, db, pasarela)
    bimestral = db.scalar(select(Plan).where(Plan.code == "bimestral"))
    token_b, _, _ = _cuenta(client, db)
    _aprobar(client, pasarela, _abrir_pago(client, db, token_b, plan=bimestral))
    # Un pago rechazado y uno abierto sin completar.
    rechazado = _abrir_pago(client, db, _cuenta(client, db)[0])
    assert _webhook(client, pasarela.evento(pasarela.transaccion(rechazado, "DECLINED"))).status_code == 200
    _abrir_pago(client, db, _cuenta(client, db)[0])

    data = _resumen(client, admin_token)
    subs = data["subscriptions"]
    assert (subs["active"], subs["pending"], subs["in_force"], subs["canceled"]) == (3, 2, 3, 0)
    [recurrente] = data["recurring"]
    # El bimestral cuenta la mitad: 150.000 COP cada dos meses son 75.000 al mes.
    assert recurrente == {
        "currency": "COP",
        "total_cents": PRECIO + PRECIO + 7_500_000,
        "automatic_cents": PRECIO,
        "manual_cents": PRECIO + 7_500_000,
        "subscriptions": 3,
    }
    assert data["new_subscriptions"]["current"] == 3
    assert data["failed_charges"]["current"] == 1
    [cobrado] = data["collected"]
    assert (cobrado["currency"], cobrado["current_cents"]) == ("COP", 2 * PRECIO + 15_000_000)
    assert data["cancellations"]["current"] == 0

    # Un reembolso registrado descuenta de lo cobrado; una cancelacion sale del
    # recurrente y cuenta en el periodo.
    [pago_manual] = _pagos(db, str(manual.user_id))
    assert _reembolso(client, admin_token, pago_manual.id).status_code == 201
    assert _accion(client, admin_token, automatica.id, "cancel_at_period_end").status_code == 200

    data = _resumen(client, admin_token)
    assert data["collected"][0]["current_cents"] == 2 * PRECIO + 15_000_000 - 4_000_000
    assert data["cancellations"]["current"] == 1
    assert data["subscriptions"]["canceled"] == 1
    assert data["recurring"][0]["automatic_cents"] == 0
    assert data["recurring"][0]["subscriptions"] == 2
    # Sin suscripciones vigentes al empezar el mes no hay base para la tasa.
    assert data["cancellation_rate"]["current_bp"] is None


def test_el_mes_anterior_se_compara_con_el_mismo_tramo(client, db, pasarela, admin_token: str) -> None:
    _, _, _, manual = _suscriptor_manual(client, db, pasarela)
    _, _, _, otra = _suscriptor_manual(client, db, pasarela)
    p = periods(datetime.now(UTC))
    mitad_anterior = p.previous.start + (p.previous.end - p.previous.start) / 2
    # El pago de una cae en el tramo anterior, y su periodo cubria el inicio de
    # este mes: es la base de la tasa de cancelacion.
    [pago] = _pagos(db, str(otra.user_id))
    db.execute(
        text(
            "UPDATE payments SET resolved_at = :r, period_start = :s, period_end = :e WHERE id = :id"
        ),
        {
            "r": mitad_anterior,
            "s": p.current.start - timedelta(days=1),
            "e": p.current.start + timedelta(days=29),
            "id": pago.id,
        },
    )
    db.commit()
    assert _accion(client, admin_token, otra.id, "cancel_now").status_code == 200

    data = _resumen(client, admin_token)
    assert data["new_subscriptions"] == {"current": 1, "previous": 1}
    assert data["collected"][0] == {
        "currency": "COP",
        "current_cents": PRECIO,
        "previous_cents": PRECIO,
    }
    assert data["cancellations"] == {"current": 1, "previous": 0}
    # Una cancelada de una vigente al empezar el mes: 100 %.
    assert data["cancellation_rate"]["current_bp"] == 10_000
    # Lo del mes anterior despues de "ahora en el mes anterior" no cuenta.
    db.execute(
        text("UPDATE payments SET resolved_at = :r WHERE id = :id"),
        {"r": p.previous.end + timedelta(seconds=1), "id": pago.id},
    )
    db.commit()
    data = _resumen(client, admin_token)
    assert data["new_subscriptions"]["previous"] == 0


def test_registros_y_correos_confirmados(client, db, admin_token: str) -> None:
    antes = _resumen(client, admin_token)
    _cuenta(client, db, verificada=True)
    _cuenta(client, db, verificada=False)
    despues = _resumen(client, admin_token)
    assert despues["registrations"]["current"] - antes["registrations"]["current"] == 2
    assert (
        despues["verified_registrations"]["current"] - antes["verified_registrations"]["current"]
        == 1
    )


# ---------- Forzar el restablecimiento de la contrasena ----------


def _link(message) -> str:
    match = re.search(r"[?&]token=([A-Za-z0-9_-]+)", message.text)
    assert match, message.text
    return match.group(1)


def test_forzar_el_restablecimiento_cierra_sesiones_y_anula_la_contrasena(
    client, db, admin_token: str, outbox
) -> None:
    token, user_id, correo = _cuenta(client, db)
    login = {"email": correo, "password": "clave-segura-123"}
    refresh = client.post("/auth/login", json=login).json()["refresh_token"]
    outbox.clear()

    r = client.post(
        f"/admin/users/{user_id}/force-password-reset",
        json={"reason": MOTIVO},
        headers=auth(admin_token),
    )
    assert r.status_code == 200, r.text

    # Sus sesiones se cerraron y la contrasena de siempre ya no sirve.
    assert client.get("/auth/me", headers=auth(token)).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": refresh}).status_code == 401
    assert client.post("/auth/login", json=login).status_code == 401

    [fila] = _filas(db, "user.password.force_reset", user_id)
    assert (fila.reason, fila.after["token_version"]) == (MOTIVO, fila.before["token_version"] + 1)
    # La bitacora no guarda nada de la contrasena.
    assert "password" not in str(fila.before) + str(fila.after)

    [aviso] = [m for m in outbox if m.to == correo]
    assert aviso.subject == "Elige una contraseña nueva para tu cuenta de Sebasanálisis"
    assert "/restablecer-contrasena?token=" in aviso.text and MOTIVO not in aviso.text

    # Con el enlace elige una nueva y vuelve a entrar.
    r = client.post(
        "/auth/reset-password",
        json={"token": _link(aviso), "new_password": "otra-clave-larga-987"},
    )
    assert r.status_code == 200, r.text
    nueva = {"email": correo, "password": "otra-clave-larga-987"}
    assert client.post("/auth/login", json=nueva).status_code == 200


@pytest.mark.parametrize("cuerpo", [{}, {"reason": ""}, {"reason": "no"}])
def test_forzar_el_restablecimiento_sin_motivo_se_rechaza(
    client, db, admin_token: str, cuerpo
) -> None:
    token, user_id, _ = _cuenta(client, db)
    r = client.post(
        f"/admin/users/{user_id}/force-password-reset", json=cuerpo, headers=auth(admin_token)
    )
    assert r.status_code == 422
    assert _filas(db, "user.password.force_reset", user_id) == []
    assert client.get("/auth/me", headers=auth(token)).status_code == 200


def test_forzar_el_restablecimiento_no_aplica_a_uno_mismo_ni_a_quien_no_es_admin(
    client, db, admin_token: str, user_token: str
) -> None:
    admin_id = client.get("/auth/me", headers=auth(admin_token)).json()["id"]
    r = client.post(
        f"/admin/users/{admin_id}/force-password-reset",
        json={"reason": MOTIVO},
        headers=auth(admin_token),
    )
    assert r.status_code == 409
    assert client.get("/auth/me", headers=auth(admin_token)).status_code == 200

    _, user_id, _ = _cuenta(client, db)
    url = f"/admin/users/{user_id}/force-password-reset"
    assert client.post(url, json={"reason": MOTIVO}, headers=auth(user_token)).status_code == 403
    assert client.post(url, json={"reason": MOTIVO}).status_code == 401
    assert (
        client.post(
            f"/admin/users/{uuid.uuid4()}/force-password-reset",
            json={"reason": MOTIVO},
            headers=auth(admin_token),
        ).status_code
        == 404
    )


# ---------- Reenviar la verificacion ----------


def test_reenviar_la_verificacion_envia_el_enlace_y_deja_fila(
    client, db, admin_token: str, outbox
) -> None:
    _, user_id, correo = _cuenta(client, db, verificada=False)
    outbox.clear()
    url = f"/admin/users/{user_id}/resend-verification"

    r = client.post(url, headers=auth(admin_token))
    assert r.status_code == 200, r.text
    [correo_enviado] = [m for m in outbox if m.to == correo]
    assert correo_enviado.subject == "Confirma tu correo en Sebasanálisis"
    [fila] = _filas(db, "user.verification.resend", user_id)
    assert fila.reason is None and fila.target_type == "user"

    # Un segundo clic dentro del minuto no manda otro correo.
    assert client.post(url, headers=auth(admin_token)).status_code == 429
    assert len([m for m in outbox if m.to == correo]) == 1

    # El enlace confirma el correo; despues ya no hay nada que reenviar.
    assert client.post("/auth/verify-email", json={"token": _link(correo_enviado)}).status_code == 200
    from app.core import rate_limit

    rate_limit.reset_all()
    r = client.post(url, headers=auth(admin_token))
    assert r.status_code == 409


def test_reenviar_la_verificacion_es_solo_para_administradores(
    client, db, user_token: str, admin_token: str
) -> None:
    _, user_id, _ = _cuenta(client, db, verificada=False)
    url = f"/admin/users/{user_id}/resend-verification"
    assert client.post(url, headers=auth(user_token)).status_code == 403
    assert client.post(url).status_code == 401
    assert client.post(f"/admin/users/{uuid.uuid4()}/resend-verification", headers=auth(admin_token)).status_code == 404
