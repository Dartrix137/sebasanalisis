"""Las facturas de los pagos de prueba se apartan antes de encender Siigo
(`core/sandbox_payments.py`, `scripts/cancel_test_invoices.py`; decidido por el
usuario el 2026-11-13).

Los pagos aprobados en el sandbox de Tipster Page tienen su factura `pending`, y
con la emision encendida en la empresa real saldrian a la DIAN.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.core import sandbox_payments
from app.models import AdminAuditLog, Invoice, User
from tests.api.test_subscriptions import _abrir_pago, _aprobar, _cuenta, _pagos

MOTIVO = "Pagos de prueba del sandbox de Tipster Page"


def _pago_aprobado(client, db, tipster):
    token, user_id, _ = _cuenta(client, db)
    _aprobar(client, tipster, _abrir_pago(client, db, token))
    [pago] = _pagos(db, user_id)
    return pago


def _factura(db, payment_id) -> Invoice:
    db.expire_all()
    return db.scalar(select(Invoice).where(Invoice.payment_id == payment_id))


def _admin(db, admin_token) -> User:
    return db.scalar(select(User).where(User.role == "admin").order_by(User.created_at.desc()))


def _mover_aprobacion(db, payment_id, cuando: datetime) -> None:
    db.execute(
        text("UPDATE payments SET resolved_at = :c WHERE id = :p"), {"c": cuando, "p": payment_id}
    )
    db.commit()


def test_aparta_solo_las_de_pagos_de_prueba_nunca_enviadas(
    client, db, tipster, admin_token
) -> None:
    ahora = datetime.now(UTC)
    corte = ahora - timedelta(hours=1)
    prueba = _pago_aprobado(client, db, tipster)
    _mover_aprobacion(db, prueba.id, corte - timedelta(days=8))
    # Una que ya se intento enviar pudo llegar a Siigo: la mira una persona.
    intentada = _pago_aprobado(client, db, tipster)
    _mover_aprobacion(db, intentada.id, corte - timedelta(days=7))
    db.execute(text("UPDATE invoices SET attempts = 1 WHERE payment_id = :p"), {"p": intentada.id})
    db.commit()
    # Aprobado despues del corte: es real y su factura tiene que salir.
    real = _pago_aprobado(client, db, tipster)

    candidatas = sandbox_payments.candidates(db, corte)
    assert [c.payment_id for c in candidatas] == [prueba.id]
    assert (candidatas[0].amount_cents, candidatas[0].currency) == (3200, "EUR")

    admin = _admin(db, admin_token)
    hechas = sandbox_payments.cancel(db, admin, corte, f"  {MOTIVO}  ", ahora)
    db.commit()
    assert [h.payment_id for h in hechas] == [prueba.id]

    apartada = _factura(db, prueba.id)
    assert (apartada.status, apartada.cancel_reason) == ("cancelled", "test_payment")
    assert apartada.cancelled_at is not None
    assert _factura(db, intentada.id).status == "pending"
    assert _factura(db, real.id).status == "pending"

    [fila] = db.scalars(
        select(AdminAuditLog).where(AdminAuditLog.action == "invoice.cancel_test_payment")
    ).all()
    assert (fila.target_type, fila.target_id, fila.reason) == ("payment", str(prueba.id), MOTIVO)
    assert fila.admin_email == admin.email
    assert fila.after == {"status": "cancelled", "cancel_reason": "test_payment"}

    # Otra corrida no hace nada: ya no queda ninguna.
    assert sandbox_payments.candidates(db, corte) == []
    assert sandbox_payments.cancel(db, admin, corte, MOTIVO, ahora) == []


@pytest.mark.parametrize(
    ("cambio", "error"),
    [
        ({"motivo": "  "}, "motivo"),
        ({"corte": timedelta(minutes=5)}, "futura"),
        ({"rol": "user"}, "administrador"),
    ],
)
def test_no_aparta_nada_sin_motivo_con_corte_futuro_o_sin_admin(
    client, db, tipster, admin_token, cambio, error
) -> None:
    pago = _pago_aprobado(client, db, tipster)
    ahora = datetime.now(UTC)
    admin = _admin(db, admin_token)
    if cambio.get("rol"):
        admin = db.scalar(select(User).where(User.id == pago.user_id))
    with pytest.raises(ValueError, match=error):
        sandbox_payments.cancel(
            db, admin, ahora + cambio.get("corte", timedelta(0)), cambio.get("motivo", MOTIVO), ahora
        )
    db.rollback()
    assert _factura(db, pago.id).status == "pending"


def test_la_base_acepta_el_motivo(db) -> None:
    """La migracion d7a2e5c9f1b3 amplia el CHECK de `cancel_reason`."""
    definicion = db.execute(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conname = 'invoice_cancel_reason'"
        )
    ).scalar_one()
    assert "test_payment" in definicion
