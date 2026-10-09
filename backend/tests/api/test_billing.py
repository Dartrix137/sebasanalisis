"""Planes y cotizacion (§3.3 de la Fase 4; "hecho cuando" del paso 4 en §9).

Los cupones se crean directo en la base: asi se pueden probar estados que el
admin no deja guardar (otra moneda) o que dependen del tiempo (vencido).
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Coupon, CouponRedemption, Plan, User
from tests.api.conftest import auth, register_raw

PRECIO = 10_000_000  # 100.000 COP en centavos


def _mensual(db) -> Plan:
    return db.scalar(select(Plan).where(Plan.code == "mensual"))


def _plan(db, **campos) -> Plan:
    datos = {
        "code": f"plan-{uuid.uuid4().hex[:10]}",
        "name": "Plan de prueba",
        "description": "Solo para tests.",
        "price_cents": 5_000_000,
        "currency": "COP",
        "interval": "month",
        "interval_count": 1,
        "active": True,
        "sort_order": 50,
    }
    plan = Plan(**{**datos, **campos})
    db.add(plan)
    db.commit()
    return plan


def _cupon(db, *, planes: list[Plan] | None = None, **campos) -> Coupon:
    datos = {
        "code": f"T{uuid.uuid4().hex[:10].upper()}",
        "kind": "percent",
        "value": 20,
        "currency": None,
        "duration": "once",
        "redemptions_count": 0,
        "valid_from": datetime.now(UTC) - timedelta(days=1),
        "active": True,
    }
    cupon = Coupon(**{**datos, **campos})
    cupon.plans = planes or []
    db.add(cupon)
    db.commit()
    return cupon


def _cotizar(client: TestClient, token: str, plan_id, codigo: str | None = None, **extra):
    body = {"plan_id": str(plan_id), **extra}
    if codigo is not None:
        body["coupon_code"] = codigo
    return client.post("/billing/quote", json=body, headers=auth(token))


def _rechazado(client: TestClient, token: str, db, cupon: Coupon, motivo: str) -> dict:
    """El cupon no aplica: precio completo y el motivo."""
    r = _cotizar(client, token, _mensual(db).id, cupon.code)
    assert r.status_code == 200, r.text
    data = r.json()
    assert (data["subtotal_cents"], data["discount_cents"], data["total_cents"]) == (PRECIO, 0, PRECIO)
    assert data["coupon"]["applied"] is False
    assert data["coupon"]["reason"] == motivo
    assert data["coupon"]["message"]
    return data


# ---------- GET /plans ----------


def test_los_planes_son_publicos_y_traen_el_plan_mensual(client: TestClient) -> None:
    r = client.get("/plans")
    assert r.status_code == 200
    mensual = next(p for p in r.json() if p["code"] == "mensual")
    assert mensual["name"] == "Acceso Mensual"
    assert (mensual["price_cents"], mensual["currency"]) == (10_000_000, "COP")
    # Un solo precio: no hay un precio de referencia en otra moneda.
    assert not [campo for campo in mensual if campo.startswith("display")]
    assert (mensual["interval"], mensual["interval_count"]) == ("month", 1)


def test_un_plan_desactivado_no_se_ofrece(client: TestClient, db) -> None:
    plan = _plan(db, active=False)
    assert plan.code not in [p["code"] for p in client.get("/plans").json()]


def test_la_descripcion_del_plan_no_promete_resultados(client: TestClient) -> None:
    mensual = next(p for p in client.get("/plans").json() if p["code"] == "mensual")
    texto = f"{mensual['name']} {mensual['description']}".lower()
    for prohibido in ("garantiz", "infalible", "va a salir", "seguro", "predice", "gana"):
        assert prohibido not in texto
    # "prediccion" y "ventaja" solo aparecen negadas.
    assert "no son una predicción" in texto
    assert "no cambian la ventaja de la casa" in texto


# ---------- POST /billing/quote ----------


def test_cotizar_exige_sesion(client: TestClient, db) -> None:
    r = client.post("/billing/quote", json={"plan_id": str(_mensual(db).id)})
    assert r.status_code == 401


def test_cotiza_una_cuenta_sin_acceso(client: TestClient, db) -> None:
    """Quien cotiza es justo quien todavia no tiene acceso a la mesa."""
    token = register_raw(client, f"sin-{uuid.uuid4().hex[:10]}@ejemplo.com")["access_token"]
    r = _cotizar(client, token, _mensual(db).id)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "plan_id": str(_mensual(db).id),
        "subtotal_cents": PRECIO,
        "discount_cents": 0,
        "total_cents": PRECIO,
        "currency": "COP",
        "coupon": None,
    }


def test_cupon_de_porcentaje(client: TestClient, user_token: str, db) -> None:
    cupon = _cupon(db, value=15)
    data = _cotizar(client, user_token, _mensual(db).id, cupon.code).json()
    assert (data["subtotal_cents"], data["discount_cents"], data["total_cents"]) == (
        PRECIO,
        1_500_000,
        8_500_000,
    )
    assert data["currency"] == "COP"
    assert data["coupon"] == {"code": cupon.code, "applied": True, "reason": None, "message": None}


def test_cupon_de_monto_fijo(client: TestClient, user_token: str, db) -> None:
    cupon = _cupon(db, kind="fixed_cents", value=2_000_000, currency="COP")
    data = _cotizar(client, user_token, _mensual(db).id, cupon.code).json()
    assert (data["discount_cents"], data["total_cents"]) == (2_000_000, 8_000_000)


def test_el_porcentaje_redondea_hacia_abajo(client: TestClient, user_token: str, db) -> None:
    plan = _plan(db, price_cents=999)
    cupon = _cupon(db, value=33)
    data = _cotizar(client, user_token, plan.id, cupon.code).json()
    assert (data["discount_cents"], data["total_cents"]) == (329, 670)


def test_el_codigo_se_acepta_en_minusculas_y_con_espacios(
    client: TestClient, user_token: str, db
) -> None:
    cupon = _cupon(db)
    data = _cotizar(client, user_token, _mensual(db).id, f"  {cupon.code.lower()} ").json()
    assert data["coupon"]["applied"] is True
    assert data["coupon"]["code"] == cupon.code


def test_un_codigo_vacio_cotiza_sin_cupon(client: TestClient, user_token: str, db) -> None:
    data = _cotizar(client, user_token, _mensual(db).id, "   ").json()
    assert data["coupon"] is None
    assert data["total_cents"] == PRECIO


def test_un_monto_enviado_por_el_cliente_se_ignora(client: TestClient, user_token: str, db) -> None:
    cupon = _cupon(db, value=10)
    r = _cotizar(
        client,
        user_token,
        _mensual(db).id,
        cupon.code,
        amount_cents=1,
        price_cents=1,
        subtotal_cents=1,
        total_cents=1,
        discount_cents=9_999_999,
        currency="USD",
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert (data["subtotal_cents"], data["discount_cents"], data["total_cents"]) == (
        PRECIO,
        1_000_000,
        9_000_000,
    )
    assert data["currency"] == "COP"


def test_cupon_vencido(client: TestClient, user_token: str, db) -> None:
    cupon = _cupon(db, valid_until=datetime.now(UTC) - timedelta(minutes=1))
    _rechazado(client, user_token, db, cupon, "expired")


def test_cupon_que_todavia_no_empieza(client: TestClient, user_token: str, db) -> None:
    cupon = _cupon(db, valid_from=datetime.now(UTC) + timedelta(days=1))
    _rechazado(client, user_token, db, cupon, "not_started")


def test_cupon_agotado(client: TestClient, user_token: str, db) -> None:
    cupon = _cupon(db, max_redemptions=3, redemptions_count=3)
    _rechazado(client, user_token, db, cupon, "exhausted")


def test_cupon_de_otro_plan(client: TestClient, user_token: str, db) -> None:
    otro = _plan(db)
    cupon = _cupon(db, planes=[otro])
    _rechazado(client, user_token, db, cupon, "other_plan")
    # En su plan si aplica.
    data = _cotizar(client, user_token, otro.id, cupon.code).json()
    assert data["coupon"]["applied"] is True
    assert data["discount_cents"] == 1_000_000


def test_cupon_ya_usado_por_el_usuario(client: TestClient, db) -> None:
    registro = register_raw(client, f"uso-{uuid.uuid4().hex[:10]}@ejemplo.com")
    cupon = _cupon(db)
    db.add(CouponRedemption(coupon_id=cupon.id, user_id=uuid.UUID(registro["user"]["id"])))
    db.commit()
    _rechazado(client, registro["access_token"], db, cupon, "already_used")


def test_el_cupon_que_uso_otra_cuenta_sigue_sirviendo(
    client: TestClient, user_token: str, db
) -> None:
    otra = register_raw(client, f"otra-{uuid.uuid4().hex[:10]}@ejemplo.com")
    cupon = _cupon(db)
    db.add(CouponRedemption(coupon_id=cupon.id, user_id=uuid.UUID(otra["user"]["id"])))
    db.commit()
    data = _cotizar(client, user_token, _mensual(db).id, cupon.code).json()
    assert data["coupon"]["applied"] is True


def test_cupon_de_otra_moneda(client: TestClient, user_token: str, db) -> None:
    cupon = _cupon(db, kind="fixed_cents", value=500, currency="USD")
    _rechazado(client, user_token, db, cupon, "currency_mismatch")


def test_cupon_inactivo(client: TestClient, user_token: str, db) -> None:
    cupon = _cupon(db, active=False)
    _rechazado(client, user_token, db, cupon, "inactive")


def test_codigo_que_no_existe(client: TestClient, user_token: str, db) -> None:
    r = _cotizar(client, user_token, _mensual(db).id, "NOEXISTE-123")
    data = r.json()
    assert r.status_code == 200
    assert data["coupon"] == {
        "code": "NOEXISTE-123",
        "applied": False,
        "reason": "not_found",
        "message": "Ese código no existe.",
    }
    assert data["total_cents"] == PRECIO


def test_un_cupon_que_cubre_todo_el_precio_no_aplica(
    client: TestClient, user_token: str, db
) -> None:
    """El total nunca queda en cero (§10 n.º 6)."""
    cupon = _cupon(db, kind="fixed_cents", value=PRECIO, currency="COP")
    _rechazado(client, user_token, db, cupon, "covers_total")
    mayor = _cupon(db, kind="fixed_cents", value=PRECIO * 3, currency="COP")
    _rechazado(client, user_token, db, mayor, "covers_total")


def test_la_base_no_acepta_un_cupon_del_100_por_ciento(db) -> None:
    import pytest
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        _cupon(db, value=100)
    db.rollback()


def test_cotizar_no_redime_el_cupon(client: TestClient, user_token: str, db) -> None:
    cupon = _cupon(db, max_redemptions=1)
    for _ in range(3):
        assert _cotizar(client, user_token, _mensual(db).id, cupon.code).json()["coupon"]["applied"]
    db.refresh(cupon)
    assert cupon.redemptions_count == 0
    assert db.scalar(select(CouponRedemption).where(CouponRedemption.coupon_id == cupon.id)) is None


def test_cotizar_no_da_acceso(client: TestClient, db) -> None:
    registro = register_raw(client, f"nada-{uuid.uuid4().hex[:10]}@ejemplo.com")
    _cotizar(client, registro["access_token"], _mensual(db).id)
    me = client.get("/auth/me", headers=auth(registro["access_token"])).json()
    assert me["access"] == {"granted": False, "reason": "no_access", "until": None}
    assert db.get(User, uuid.UUID(registro["user"]["id"])).access_type == "none"


def test_plan_que_no_existe_o_esta_desactivado(client: TestClient, user_token: str, db) -> None:
    assert _cotizar(client, user_token, uuid.uuid4()).status_code == 404
    assert _cotizar(client, user_token, _plan(db, active=False).id).status_code == 404


def test_la_cotizacion_exige_el_plan(client: TestClient, user_token: str) -> None:
    r = client.post("/billing/quote", json={"coupon_code": "X"}, headers=auth(user_token))
    assert r.status_code == 422


# ---------- Limite de intentos con codigo (§5.7.1) ----------


def test_limite_de_intentos_con_codigo_por_cuenta(client: TestClient, user_token: str, db) -> None:
    plan_id = _mensual(db).id
    for i in range(10):
        assert _cotizar(client, user_token, plan_id, f"ADIVINA-{i}").status_code == 200
    r = _cotizar(client, user_token, plan_id, "ADIVINA-10")
    assert r.status_code == 429
    # Tampoco con un codigo que si existe: el limite es de intentos.
    assert _cotizar(client, user_token, plan_id, _cupon(db).code).status_code == 429
    # Sin codigo se sigue cotizando.
    assert _cotizar(client, user_token, plan_id).status_code == 200


def test_cotizar_sin_codigo_no_gasta_intentos(client: TestClient, user_token: str, db) -> None:
    plan_id = _mensual(db).id
    for _ in range(25):
        assert _cotizar(client, user_token, plan_id).status_code == 200
    assert _cotizar(client, user_token, plan_id, "UNO").status_code == 200


def test_limite_de_intentos_con_codigo_por_ip(client: TestClient, db) -> None:
    """Crear cuentas es gratis: el limite por cuenta solo no frena adivinar."""
    plan_id = _mensual(db).id
    for _ in range(3):
        token = register_raw(client, f"ip-{uuid.uuid4().hex[:10]}@ejemplo.com")["access_token"]
        for i in range(10):
            assert _cotizar(client, token, plan_id, f"X-{i}").status_code == 200
    nueva = register_raw(client, f"ip-{uuid.uuid4().hex[:10]}@ejemplo.com")["access_token"]
    assert _cotizar(client, nueva, plan_id, "X-0").status_code == 429
