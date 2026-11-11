"""Las notas credito y las facturas que no se emiten (docs/PLATAFORMA_COMPLETA.md
§3.17, "Paso 5.4", punto 12; core/credit_notes.py).

Lo que respondio la contadora el 2026-11-11, caso por caso. El pago va por
Tipster Page o por la pasarela simulada (la anulacion, que Tipster Page no
tiene) y la factura por el emisor de Siigo de verdad sobre su transporte
simulado. Datos de clientes inventados.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.billing import fx
from app.billing.invoice_document import idempotency_key
from app.core.invoices import run_emission
from app.models import AdminAuditLog, CreditNote, Invoice
from tests.api.conftest import auth
from tests.api.siigo_sandbox import FORMA_DE_PAGO, NOTA_CREDITO, PRODUCTO, Falla
from tests.api.test_invoice_emission import CENTAVOS, PESOS, _factura, _pago_aprobado
from tests.api.test_subscriptions import _abrir_pago, _cuenta, _pagos, _webhook

MOTIVO = "El cliente pidió la devolución"
TASAS = fx.Rates(eur_usd=Decimal("1.1165"), usd_cop=Decimal("3228.26"))


def _notas(db, invoice_id) -> list[CreditNote]:
    db.expire_all()
    return list(
        db.scalars(
            select(CreditNote)
            .where(CreditNote.invoice_id == invoice_id)
            .order_by(CreditNote.created_at, CreditNote.id)
        )
    )


def _reembolso(client, admin_token, pago, monto: int, motivo: str = MOTIVO):
    return client.post(
        f"/admin/payments/{pago.id}/refunds",
        json={
            "amount_cents": monto,
            "refunded_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            "reason": motivo,
        },
        headers=auth(admin_token),
    )


def _correr(db, siigo, now=None, **kwargs):
    return run_emission(db, siigo.issuer, siigo.tasas, now or datetime.now(UTC), **kwargs)


def _anulado_por_la_pasarela(client, db, pasarela):
    """Un pago aprobado en la pasarela simulada, y despues anulado por ella."""
    token, user_id, _ = _cuenta(client, db)
    pago = _abrir_pago(client, db, token)
    tx = pasarela.transaccion(pago, "APPROVED")
    assert _webhook(client, pasarela.evento(tx)).status_code == 200
    [pago] = _pagos(db, user_id)

    def anular():
        pasarela.resolver(tx, "VOIDED")
        assert _webhook(client, pasarela.evento(tx, timestamp=1_760_000_500)).status_code == 200

    return pago, tx, anular


# ---------- Reembolso con la factura aceptada ----------


def test_un_reembolso_total_lleva_nota_credito_con_motivo_2(
    client, db, tipster, siigo, admin_token
) -> None:
    pago, _ = _pago_aprobado(client, db, tipster)
    factura = _factura(db, pago.id)
    assert factura.status == "accepted"

    r = _reembolso(client, admin_token, pago, pago.amount_cents)
    assert r.status_code == 201, r.text
    [nota] = r.json()["credit_notes"]
    assert nota["status"] == "accepted" and nota["reason"] == 2
    assert nota["provider_name"] == "NC-1-1" and nota["cude"]
    # El mismo valor en pesos de la factura (la contadora).
    assert nota["cop_cents"] == CENTAVOS == factura.cop_cents

    [crear] = siigo.pedidos_a("POST", "/v1/credit-notes")
    cuerpo = siigo.cuerpo(crear)
    assert cuerpo["document"] == {"id": NOTA_CREDITO}
    assert cuerpo["invoice"] == factura.provider_id and cuerpo["reason"] == 2
    assert cuerpo["items"] == [{"code": PRODUCTO, "description": factura.description,
                                "quantity": 1, "price": float(PESOS)}]
    assert cuerpo["payments"] == [{"id": FORMA_DE_PAGO, "value": float(PESOS)}]
    assert cuerpo["stamp"] == {"send": True} and cuerpo["mail"] == {"send": True}
    assert cuerpo["date"] == fx.operation_date(datetime.now(UTC)).isoformat()
    assert "Nota crédito de la factura FV-4-1" in cuerpo["observations"]
    assert "por reembolso total" in cuerpo["observations"]
    [db_nota] = _notas(db, factura.id)
    assert crear.headers["Idempotency-Key"] == idempotency_key(db_nota.id, "NC")
    assert crear.headers["Idempotency-Key"] != factura.idempotency_key

    [fila] = db.scalars(
        select(AdminAuditLog).where(
            AdminAuditLog.action == "payment.refund.record",
            AdminAuditLog.target_id == str(pago.id),
        )
    ).all() or [None]
    assert fila is not None and fila.after["invoice"] == "credit_note"
    assert fila.after["credit_note_id"] == str(db_nota.id)


def test_un_reembolso_parcial_usa_el_motivo_1_y_las_tasas_de_la_factura(
    client, db, tipster, siigo, admin_token
) -> None:
    pago, _ = _pago_aprobado(client, db, tipster)
    factura = _factura(db, pago.id)
    # La tasa del dia del reembolso es otra: no se usa (la contadora).
    siigo.tasas.trm = Decimal("4100.00")

    r = _reembolso(client, admin_token, pago, 1_000)
    assert r.status_code == 201, r.text
    [nota] = r.json()["credit_notes"]
    assert nota["reason"] == 1 and nota["status"] == "accepted"
    assert nota["cop_cents"] == fx.to_cop_cents(1_000, "EUR", TASAS) == 3604352

    # El resto, en otro reembolso: tambien motivo 1, y entre los dos suman la factura.
    r = _reembolso(client, admin_token, pago, pago.amount_cents - 1_000)
    assert r.status_code == 201, r.text
    primera, segunda = r.json()["credit_notes"]
    assert segunda["reason"] == 1
    assert primera["cop_cents"] + segunda["cop_cents"] == factura.cop_cents
    assert "por reembolso parcial" in siigo.cuerpo(siigo.pedidos_a("POST", "/v1/credit-notes")[1])[
        "observations"
    ]


# ---------- Antes de emitir ----------


def test_un_reembolso_total_antes_de_emitir_cancela_la_factura(
    client, db, tipster, siigo, admin_token
) -> None:
    """La contadora: "lo mejor seria no emitir la factura"."""
    siigo.tasas.publicadas = False  # la factura se queda pendiente
    pago, _ = _pago_aprobado(client, db, tipster)
    assert _factura(db, pago.id).status == "pending"

    r = _reembolso(client, admin_token, pago, pago.amount_cents)
    assert r.status_code == 201, r.text
    factura = r.json()["invoice"]
    assert factura["status"] == "cancelled" and factura["cancel_reason"] == "refunded"
    assert r.json()["credit_notes"] == []

    siigo.tasas.publicadas = True
    _correr(db, siigo, now=datetime.now(UTC) + timedelta(days=1))
    assert _factura(db, pago.id).status == "cancelled"
    assert siigo.pedidos_a("POST", "/v1/invoices") == []
    assert siigo.pedidos_a("POST", "/v1/credit-notes") == []


def test_un_reembolso_parcial_antes_de_emitir_emite_la_factura_y_despues_la_nota(
    client, db, tipster, siigo, admin_token
) -> None:
    """Decidido por el usuario el 2026-11-11: la factura por el total y la nota
    con motivo 1; sin factura, lo que no se devolvio quedaria sin facturar."""
    siigo.tasas.publicadas = False
    pago, _ = _pago_aprobado(client, db, tipster)

    r = _reembolso(client, admin_token, pago, 1_000)
    assert r.status_code == 201, r.text
    [nota] = r.json()["credit_notes"]
    assert r.json()["invoice"]["status"] == "pending"
    assert nota["status"] == "pending" and nota["waiting_reason"] == "invoice_not_accepted"

    siigo.tasas.publicadas = True
    _correr(db, siigo)
    factura = _factura(db, pago.id)
    assert factura.status == "accepted" and factura.cop_cents == CENTAVOS
    [nota] = _notas(db, factura.id)
    assert nota.status == "accepted" and nota.reason == 1
    assert nota.cop_cents == fx.to_cop_cents(1_000, "EUR", TASAS)


def test_otro_parcial_que_completa_el_total_antes_de_emitir_cancela_todo(
    client, db, tipster, siigo, admin_token
) -> None:
    siigo.tasas.publicadas = False
    pago, _ = _pago_aprobado(client, db, tipster)
    assert _reembolso(client, admin_token, pago, 1_000).status_code == 201
    r = _reembolso(client, admin_token, pago, pago.amount_cents - 1_000)
    assert r.status_code == 201, r.text
    assert r.json()["invoice"]["status"] == "cancelled"
    [nota] = r.json()["credit_notes"]
    assert nota["status"] == "cancelled"


# ---------- La factura en camino o sin aceptar ----------


def test_una_factura_en_camino_deja_esperando_la_nota_hasta_que_la_acepten(
    client, db, tipster, siigo, admin_token
) -> None:
    siigo.estado_nuevo = "Sending"
    pago, _ = _pago_aprobado(client, db, tipster)
    assert _factura(db, pago.id).status == "issued"

    r = _reembolso(client, admin_token, pago, pago.amount_cents)
    [nota] = r.json()["credit_notes"]
    assert nota["status"] == "pending" and nota["waiting_reason"] == "invoice_not_accepted"
    assert r.json()["invoice"]["status"] == "issued"  # en Siigo: no se cancela
    assert siigo.pedidos_a("POST", "/v1/credit-notes") == []

    siigo.estado_al_consultar = "Accepted"
    _correr(db, siigo)
    factura = _factura(db, pago.id)
    assert factura.status == "accepted"
    [nota] = _notas(db, factura.id)
    assert nota.status == "accepted" and nota.reason == 2  # en la misma corrida


def test_una_rechazada_por_la_dian_se_marca_anulada_y_cancela_su_nota(
    client, db, tipster, siigo, admin_token
) -> None:
    """La contadora: nota credito "solo si la factura quedo aceptada por la
    DIAN". Una rechazada se anula en Siigo Nube y el admin lo marca."""
    siigo.estado_nuevo = "Draft"
    pago, _ = _pago_aprobado(client, db, tipster)
    siigo.estado_al_consultar = "Rejected"
    _correr(db, siigo)
    assert _factura(db, pago.id).status == "rejected"

    # Sin el reembolso entero, no se marca anulada.
    r = client.post(f"/admin/payments/{pago.id}/invoice/cancel", json={"reason": MOTIVO},
                    headers=auth(admin_token))
    assert r.status_code == 409

    r = _reembolso(client, admin_token, pago, pago.amount_cents)
    [nota] = r.json()["credit_notes"]
    assert nota["status"] == "pending" and nota["waiting_reason"] == "invoice_not_accepted"

    r = client.post(f"/admin/payments/{pago.id}/invoice/cancel",
                    json={"reason": "Anulada en Siigo Nube la FV-4-1"}, headers=auth(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["invoice"]["status"] == "cancelled"
    assert r.json()["invoice"]["cancel_reason"] == "annulled_in_siigo"
    assert [n["status"] for n in r.json()["credit_notes"]] == ["cancelled"]
    [fila] = [a for a in r.json()["audit"] if a["action"] == "invoice.cancel"]
    assert fila["before"]["status"] == "rejected"
    assert siigo.pedidos_a("POST", "/v1/credit-notes") == []


def test_una_aceptada_no_se_marca_anulada(client, db, tipster, siigo, admin_token) -> None:
    pago, _ = _pago_aprobado(client, db, tipster)
    _reembolso(client, admin_token, pago, pago.amount_cents)
    r = client.post(f"/admin/payments/{pago.id}/invoice/cancel", json={"reason": MOTIVO},
                    headers=auth(admin_token))
    assert r.status_code == 409


# ---------- Anulacion de la pasarela ----------


def test_una_anulacion_con_la_factura_aceptada_lleva_nota_credito(
    client, db, pasarela, siigo
) -> None:
    """La contadora: con la factura aceptada, nota credito igual que un
    reembolso total; si no, "contara como ingreso, aunque no este el dinero"."""
    pago, tx, anular = _anulado_por_la_pasarela(client, db, pasarela)
    factura = _factura(db, pago.id)
    assert factura.status == "accepted"

    anular()
    [nota] = _notas(db, factura.id)
    assert nota.refund_id is None and nota.reason == 2 and nota.amount_cents == pago.amount_cents
    assert nota.status == "pending"  # la emite el job de cada hora
    _correr(db, siigo)
    [nota] = _notas(db, factura.id)
    assert nota.status == "accepted" and nota.cop_cents == factura.cop_cents

    # El mismo aviso otra vez no deja otra nota.
    assert _webhook(client, pasarela.evento(tx, timestamp=1_760_000_500)).status_code == 200
    assert _webhook(client, pasarela.evento(tx, timestamp=1_760_000_900)).status_code == 200
    assert len(_notas(db, factura.id)) == 1


def test_una_anulacion_antes_de_emitir_cancela_la_factura(client, db, pasarela, siigo) -> None:
    siigo.tasas.publicadas = False
    pago, _, anular = _anulado_por_la_pasarela(client, db, pasarela)
    assert _factura(db, pago.id).status == "pending"

    anular()
    factura = _factura(db, pago.id)
    assert factura.status == "cancelled" and factura.cancel_reason == "voided"
    assert _notas(db, factura.id) == []


def test_una_anulacion_despues_de_un_parcial_devuelve_lo_que_falta(
    client, db, pasarela, siigo, admin_token
) -> None:
    pago, _, anular = _anulado_por_la_pasarela(client, db, pasarela)
    assert _reembolso(client, admin_token, pago, 1_000).status_code == 201
    anular()
    factura = _factura(db, pago.id)
    primera, segunda = _notas(db, factura.id)
    assert (primera.amount_cents, primera.reason) == (1_000, 1)
    assert (segunda.amount_cents, segunda.reason) == (pago.amount_cents - 1_000, 1)
    _correr(db, siigo)
    primera, segunda = _notas(db, factura.id)
    assert primera.cop_cents + segunda.cop_cents == factura.cop_cents


# ---------- La espera de la contadora (INVOICE_HOLD_HOURS) ----------


def test_con_espera_la_factura_sale_despues_y_un_reembolso_en_el_plazo_la_cancela(
    client, db, tipster, siigo, admin_token
) -> None:
    pago, _ = _pago_aprobado(client, db, tipster)
    db.execute(Invoice.__table__.delete().where(Invoice.payment_id == pago.id))
    db.commit()
    # Se reconstruye la factura pendiente como la deja el pago.
    from app.core import invoices

    db.add(Invoice(payment_id=pago.id, status="pending",
                   operation_date=fx.operation_date(pago.resolved_at)))
    db.commit()

    espera = timedelta(hours=48)
    _correr(db, siigo, hold=espera)
    factura = _factura(db, pago.id)
    assert factura.status == "pending" and factura.waiting_reason == invoices.WAITING_HOLD
    assert factura.next_attempt_at == pago.resolved_at + espera
    antes = len(siigo.pedidos_a("POST", "/v1/invoices"))

    _correr(db, siigo, now=pago.resolved_at + espera + timedelta(minutes=1), hold=espera)
    assert _factura(db, pago.id).status == "accepted"
    assert len(siigo.pedidos_a("POST", "/v1/invoices")) == antes + 1


def test_un_reembolso_durante_la_espera_cancela_la_factura(
    client, db, tipster, siigo, admin_token, monkeypatch
) -> None:
    from app.core import invoices

    monkeypatch.setattr(invoices, "hold_period", lambda: timedelta(hours=48))
    pago, _ = _pago_aprobado(client, db, tipster)
    factura = _factura(db, pago.id)
    assert factura.status == "pending" and factura.waiting_reason == invoices.WAITING_HOLD
    assert siigo.pedidos_a("POST", "/v1/invoices") == []

    r = _reembolso(client, admin_token, pago, pago.amount_cents)
    assert r.json()["invoice"]["status"] == "cancelled"
    _correr(db, siigo, now=datetime.now(UTC) + timedelta(days=3))
    assert siigo.pedidos_a("POST", "/v1/invoices") == []


# ---------- Errores y configuracion ----------


def test_sin_el_tipo_de_nota_credito_la_nota_espera(client, db, tipster, siigo, admin_token) -> None:
    siigo.issuer.credit_note_document_type_id = 0
    pago, _ = _pago_aprobado(client, db, tipster)
    r = _reembolso(client, admin_token, pago, pago.amount_cents)
    [nota] = r.json()["credit_notes"]
    assert nota["status"] == "pending" and nota["waiting_reason"] == "credit_note_type_missing"
    assert siigo.pedidos_a("POST", "/v1/credit-notes") == []


def test_un_tiempo_agotado_reintenta_la_nota_con_la_misma_llave(
    client, db, tipster, siigo, admin_token
) -> None:
    pago, _ = _pago_aprobado(client, db, tipster)
    siigo.fallar("POST", "/v1/credit-notes", Falla(0, timeout=True))
    r = _reembolso(client, admin_token, pago, pago.amount_cents)
    [nota] = r.json()["credit_notes"]
    assert nota["status"] == "sending"

    factura = _factura(db, pago.id)
    [db_nota] = _notas(db, factura.id)
    _correr(db, siigo, now=db_nota.next_attempt_at + timedelta(seconds=1))
    [db_nota] = _notas(db, factura.id)
    assert db_nota.status == "accepted" and db_nota.attempts == 2
    llaves = {p.headers["Idempotency-Key"] for p in siigo.pedidos_a("POST", "/v1/credit-notes")}
    assert llaves == {db_nota.idempotency_key} and len(siigo.notas) == 1


def test_un_error_de_datos_la_deja_fallida_y_el_admin_la_reintenta(
    client, db, tipster, siigo, admin_token
) -> None:
    pago, _ = _pago_aprobado(client, db, tipster)
    siigo.fallar("POST", "/v1/credit-notes", Falla(400, ["invalid_document"], "No enviada"))
    r = _reembolso(client, admin_token, pago, pago.amount_cents)
    [nota] = r.json()["credit_notes"]
    assert nota["status"] == "failed" and nota["last_error_codes"] == ["invalid_document"]

    r = client.post(f"/admin/payments/{pago.id}/credit-notes/{nota['id']}/retry",
                    json={"reason": "Corregido en Siigo Nube"}, headers=auth(admin_token))
    assert r.status_code == 200, r.text
    [nota] = r.json()["credit_notes"]
    assert nota["status"] == "accepted"
    primero, segundo = siigo.pedidos_a("POST", "/v1/credit-notes")
    assert primero.headers["Idempotency-Key"] != segundo.headers["Idempotency-Key"]
    [fila] = [a for a in r.json()["audit"] if a["action"] == "credit_note.retry"]
    assert fila["before"]["status"] == "failed"


def test_una_nota_rechazada_se_reconsulta(client, db, tipster, siigo, admin_token) -> None:
    siigo.estado_nota = "Draft"
    pago, _ = _pago_aprobado(client, db, tipster)
    r = _reembolso(client, admin_token, pago, pago.amount_cents)
    [nota] = r.json()["credit_notes"]
    assert nota["status"] == "issued"

    siigo.estado_nota_al_consultar = "Rejected"
    _correr(db, siigo)
    factura = _factura(db, pago.id)
    assert [n.status for n in _notas(db, factura.id)] == ["rejected"]

    siigo.estado_nota_al_consultar = "Accepted"
    r = client.post(f"/admin/payments/{pago.id}/credit-notes/{nota['id']}/refresh",
                    json={"reason": "Reenviada desde Siigo Nube"}, headers=auth(admin_token))
    assert r.status_code == 200, r.text
    [nota] = r.json()["credit_notes"]
    assert nota["status"] == "accepted" and nota["cude"]


def test_una_nota_de_otro_pago_no_se_toca(client, db, tipster, siigo, admin_token) -> None:
    pago, _ = _pago_aprobado(client, db, tipster)
    otro, _ = _pago_aprobado(client, db, tipster)
    [nota] = _reembolso(client, admin_token, pago, pago.amount_cents).json()["credit_notes"]
    r = client.post(f"/admin/payments/{otro.id}/credit-notes/{nota['id']}/refresh",
                    json={"reason": MOTIVO}, headers=auth(admin_token))
    assert r.status_code == 404
