"""La factura pendiente de cada pago aprobado (docs/PLATAFORMA_COMPLETA.md §3.17;
Fase 5, paso 5.2).

Nace en la misma transaccion en que `apply_transaction` aprueba el pago, es
unica por pago y se queda en `pending`: la emision con Dataico es del paso 5.4.
La pasarela es el doble de `pasarela_double.py`, salvo en el caso de la pasarela
simulada.
"""

import uuid
from datetime import UTC, date, datetime

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.billing import fx
from app.core import subscriptions
from app.models import Invoice, Payment
from app.payments.base import get_payment_provider
from app.payments.fake import FakePaymentProvider
from tests.api.conftest import auth
from tests.api.test_billing import _mensual
from tests.api.test_renewals import H, _avisada, _correr, _suscriptor_automatico
from tests.api.test_subscription_changes import _eliminar
from tests.api.test_subscriptions import (
    _abrir_pago,
    _aprobar,
    _cuenta,
    _pagos,
    _suscribir,
    _tiene_acceso,
    _webhook,
)


def _facturas(db, payment_id) -> list[Invoice]:
    db.expire_all()
    return list(db.scalars(select(Invoice).where(Invoice.payment_id == payment_id)))


# ---------- Nace con el pago aprobado ----------


def test_un_pago_aprobado_deja_su_factura_pendiente(client, db, pasarela) -> None:
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    assert _facturas(db, pago.id) == []

    _aprobar(client, pasarela, pago)

    [pago] = _pagos(db, user_id)
    [factura] = _facturas(db, pago.id)
    assert factura.status == "pending"
    assert factura.operation_date == fx.operation_date(pago.resolved_at)


def test_el_dia_de_la_operacion_es_el_de_colombia(client, db, pasarela) -> None:
    """Aprobado a las 03:00 UTC del 24: en Colombia todavia es el 23."""
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    transaction = pasarela.provider.fetch_transaction(pasarela.transaccion(pago, "APPROVED"))

    subscriptions.apply_transaction(db, transaction, datetime(2026, 10, 24, 3, 0, tzinfo=UTC))

    [factura] = _facturas(db, pago.id)
    assert factura.operation_date == date(2026, 10, 23)


def test_el_mismo_webhook_varias_veces_deja_una_sola_factura(client, db, pasarela) -> None:
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    evento = pasarela.evento(pasarela.transaccion(pago, "APPROVED"))

    assert _webhook(client, evento).json() == {"status": "processed"}
    for _ in range(3):
        assert _webhook(client, evento).json() == {"status": "duplicate"}

    assert len(_facturas(db, pago.id)) == 1


def test_el_webhook_y_la_consulta_del_pago_dejan_una_sola_factura(client, db, pasarela) -> None:
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tx_id = pasarela.transaccion(pago, "APPROVED")

    # El cliente vuelve de la pasarela antes de que llegue el webhook.
    r = client.get(
        f"/billing/payments/{pago.id}", params={"transaction_id": tx_id}, headers=auth(token)
    )
    assert r.json()["status"] == "approved"
    assert _webhook(client, pasarela.evento(tx_id)).status_code == 200

    assert len(_facturas(db, pago.id)) == 1


def test_un_pago_aprobado_con_la_pasarela_simulada_deja_su_factura(client, db) -> None:
    from app.main import app

    fake = FakePaymentProvider(api_base_url="http://testserver")
    anterior = app.dependency_overrides.get(get_payment_provider)
    app.dependency_overrides[get_payment_provider] = lambda: fake
    try:
        token, user_id, _ = _cuenta(client, db)
        r = _suscribir(client, token, _mensual(db).id)
        assert r.status_code == 202, r.text
        url = httpx.URL(r.json()["checkout_url"])
        r = client.post(
            url.path, data={**dict(url.params), "outcome": "approved"}, follow_redirects=False
        )
        assert r.status_code == 303
        [pago] = _pagos(db, user_id)
        r = client.get(
            f"/billing/payments/{pago.id}",
            params={"transaction_id": httpx.URL(r.headers["location"]).params["id"]},
            headers=auth(token),
        )
        assert r.json()["status"] == "approved"
        assert _tiene_acceso(client, token)

        [factura] = _facturas(db, pago.id)
        assert factura.status == "pending"
    finally:
        app.dependency_overrides[get_payment_provider] = anterior


# ---------- Sin pago aprobado no hay factura ----------


@pytest.mark.parametrize("estado", ["DECLINED", "ERROR", "PENDING"])
def test_un_pago_que_no_se_aprueba_no_deja_factura(client, db, pasarela, estado: str) -> None:
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    assert _webhook(client, pasarela.evento(pasarela.transaccion(pago, estado))).status_code == 200
    assert _facturas(db, pago.id) == []


def test_aprobado_por_otro_monto_no_deja_factura(client, db, pasarela) -> None:
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tx_id = pasarela.transaccion(pago, "APPROVED", amount_cents=100)
    assert _webhook(client, pasarela.evento(tx_id)).status_code == 200
    [pago] = _pagos(db, user_id)
    assert pago.status == "error"
    assert _facturas(db, pago.id) == []


# ---------- Renovacion, anulacion y cuenta eliminada ----------


@pytest.fixture
def sin_suscripciones_de_otros_tests(db) -> None:
    """El job recorre todas las suscripciones de la base."""
    for tabla in ("invoices", "payment_events", "payments", "coupon_redemptions", "subscriptions"):
        db.execute(text(f"DELETE FROM {tabla}"))
    db.commit()


def test_la_renovacion_automatica_aprobada_deja_su_factura(
    client, db, pasarela, sin_suscripciones_de_otros_tests
) -> None:
    _, user_id, _, suscripcion = _suscriptor_automatico(client, db, pasarela)
    vence = _avisada(db, pasarela, suscripcion)

    assert _correr(db, pasarela, vence - 48 * H).approved == 1

    alta, renovacion = _pagos(db, user_id)
    assert renovacion.kind == "renewal"
    for pago in (alta, renovacion):
        [factura] = _facturas(db, pago.id)
        assert factura.status == "pending"
    [factura] = _facturas(db, renovacion.id)
    assert factura.operation_date == fx.operation_date(vence - 48 * H)


def test_un_pago_anulado_despues_conserva_su_factura_pendiente(client, db, pasarela) -> None:
    """Que hacer con ella (nota credito o no emitirla) lo decide el paso 5.4."""
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tx = _aprobar(client, pasarela, pago)

    pasarela.resolver(tx, "VOIDED")
    assert _webhook(client, pasarela.evento(tx, timestamp=1_760_000_500)).status_code == 200

    [pago] = _pagos(db, user_id)
    assert pago.status == "voided"
    [factura] = _facturas(db, pago.id)
    assert factura.status == "pending"


def test_la_factura_sobrevive_a_la_cuenta_eliminada(client, db, pasarela) -> None:
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    _aprobar(client, pasarela, pago)
    pago_id = pago.id

    assert _eliminar(client, token).status_code == 204

    db.expire_all()
    assert db.get(Payment, pago_id).user_id is None
    [factura] = _facturas(db, pago_id)
    assert factura.status == "pending"


def test_la_base_no_admite_dos_facturas_del_mismo_pago(client, db, pasarela) -> None:
    token, _, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    _aprobar(client, pasarela, pago)

    db.add(Invoice(payment_id=pago.id, status="pending", operation_date=date(2026, 10, 23)))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_una_factura_necesita_un_pago(db) -> None:
    db.add(Invoice(payment_id=uuid.uuid4(), status="pending", operation_date=date(2026, 10, 23)))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ---------- Admin ----------


def test_el_detalle_del_pago_en_el_admin_trae_la_factura(
    client, db, pasarela, admin_token: str
) -> None:
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)

    r = client.get(f"/admin/payments/{pago.id}", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["invoice"] is None

    _aprobar(client, pasarela, pago)
    [pago] = _pagos(db, user_id)
    r = client.get(f"/admin/payments/{pago.id}", headers=auth(admin_token))
    assert r.json()["invoice"]["status"] == "pending"
    assert r.json()["invoice"]["operation_date"] == fx.operation_date(pago.resolved_at).isoformat()
