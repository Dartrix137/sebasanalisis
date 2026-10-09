"""Admin: planes y cupones (§4.4, §4.5 y §4.6 de la Fase 4)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.models import Coupon, CouponRedemption
from tests.api.conftest import auth, register_raw

MOTIVO = "Prueba automatizada"


def _plan_body(**cambios) -> dict:
    return {
        "code": f"plan-{uuid.uuid4().hex[:10]}",
        "name": "Acceso de prueba",
        "description": "Acceso a la plataforma durante un mes.",
        "price_cents": 8_000_000,
        "currency": "COP",
        "interval": "month",
        "interval_count": 1,
        "reason": MOTIVO,
        **cambios,
    }


def _cupon_body(**cambios) -> dict:
    return {
        "code": f"T{uuid.uuid4().hex[:10]}",
        "kind": "percent",
        "value": 10,
        "duration": "once",
        "reason": MOTIVO,
        **cambios,
    }


def _crear_plan(client: TestClient, token: str, **cambios) -> dict:
    r = client.post("/admin/plans", json=_plan_body(**cambios), headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def _crear_cupon(client: TestClient, token: str, **cambios) -> dict:
    r = client.post("/admin/coupons", json=_cupon_body(**cambios), headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def _bitacora(db, target_id: str) -> list:
    return list(
        db.execute(
            text(
                "SELECT action, before, after, reason, admin_email FROM admin_audit_log "
                "WHERE target_id = :t ORDER BY created_at"
            ),
            {"t": target_id},
        )
    )


def _cotizar(client: TestClient, token: str, plan_id: str, codigo: str | None = None):
    body = {"plan_id": plan_id, **({"coupon_code": codigo} if codigo else {})}
    return client.post("/billing/quote", json=body, headers=auth(token))


# ---------- Autorizacion ----------

_RUTAS = [
    ("GET", "/admin/plans"),
    ("POST", "/admin/plans"),
    ("PATCH", f"/admin/plans/{uuid.uuid4()}"),
    ("GET", "/admin/coupons"),
    ("POST", "/admin/coupons"),
    ("PATCH", f"/admin/coupons/{uuid.uuid4()}"),
    ("GET", f"/admin/coupons/{uuid.uuid4()}/redemptions"),
]


@pytest.mark.parametrize(("method", "ruta"), _RUTAS)
def test_solo_un_administrador(client: TestClient, user_token: str, method: str, ruta: str) -> None:
    assert client.request(method, ruta, json={}).status_code == 401
    assert client.request(method, ruta, json={}, headers=auth(user_token)).status_code == 403


def test_no_hay_como_borrar_planes_ni_cupones(client: TestClient, admin_token: str) -> None:
    """Lo que ya se uso no se borra, se desactiva: no existe el DELETE."""
    plan = _crear_plan(client, admin_token)
    cupon = _crear_cupon(client, admin_token)
    h = auth(admin_token)
    assert client.delete(f"/admin/plans/{plan['id']}", headers=h).status_code == 405
    assert client.delete(f"/admin/coupons/{cupon['id']}", headers=h).status_code == 405


# ---------- Planes ----------


def test_crear_un_plan_lo_ofrece_y_deja_fila_en_la_bitacora(
    client: TestClient, admin_token: str, db
) -> None:
    plan = _crear_plan(client, admin_token, sort_order=7)
    assert plan["active"] is True
    assert (plan["price_cents"], plan["currency"]) == (8_000_000, "COP")

    assert plan["code"] in [p["code"] for p in client.get("/plans").json()]
    listado = client.get("/admin/plans", headers=auth(admin_token)).json()
    assert plan["id"] in [p["id"] for p in listado["items"]]
    assert listado["total"] >= 2  # el sembrado y este

    (fila,) = _bitacora(db, plan["id"])
    assert fila.action == "plan.create"
    assert fila.before is None
    assert fila.after["price_cents"] == 8_000_000
    assert fila.after["currency"] == "COP"
    assert fila.reason == MOTIVO
    assert fila.admin_email.startswith("admin-")


@pytest.mark.parametrize(
    "cambios",
    [
        {"reason": ""},
        {"currency": "USD"},  # solo se cobra en COP
        {"price_cents": 0},
        {"price_cents": 80_000.5},  # nunca float
        {"interval": "week"},
        {"interval_count": 0},
        {"code": "Con Espacios"},
        {"name": ""},
    ],
)
def test_un_plan_mal_formado_se_rechaza(client: TestClient, admin_token: str, cambios: dict) -> None:
    r = client.post("/admin/plans", json=_plan_body(**cambios), headers=auth(admin_token))
    assert r.status_code == 422, r.text


def test_crear_un_plan_sin_motivo_se_rechaza(client: TestClient, admin_token: str) -> None:
    body = _plan_body()
    del body["reason"]
    assert client.post("/admin/plans", json=body, headers=auth(admin_token)).status_code == 422


def test_el_codigo_de_un_plan_es_unico(client: TestClient, admin_token: str) -> None:
    plan = _crear_plan(client, admin_token)
    r = client.post("/admin/plans", json=_plan_body(code=plan["code"]), headers=auth(admin_token))
    assert r.status_code == 409


def test_cambiar_el_precio_cambia_la_cotizacion_y_queda_en_la_bitacora(
    client: TestClient, admin_token: str, user_token: str, db
) -> None:
    plan = _crear_plan(client, admin_token)
    r = client.patch(
        f"/admin/plans/{plan['id']}",
        json={"price_cents": 9_000_000, "reason": "Ajuste de precio"},
        headers=auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["price_cents"] == 9_000_000
    # Lo que no se mando no cambio.
    assert r.json()["name"] == plan["name"]

    assert _cotizar(client, user_token, plan["id"]).json()["total_cents"] == 9_000_000

    creado, editado = _bitacora(db, plan["id"])
    assert editado.action == "plan.update"
    assert editado.before["price_cents"] == 8_000_000
    assert editado.after["price_cents"] == 9_000_000
    assert editado.reason == "Ajuste de precio"


def test_desactivar_un_plan_deja_de_ofrecerlo(
    client: TestClient, admin_token: str, user_token: str, db
) -> None:
    plan = _crear_plan(client, admin_token)
    h = auth(admin_token)
    r = client.patch(f"/admin/plans/{plan['id']}", json={"active": False, "reason": MOTIVO}, headers=h)
    assert r.status_code == 200 and r.json()["active"] is False
    assert plan["code"] not in [p["code"] for p in client.get("/plans").json()]
    assert _cotizar(client, user_token, plan["id"]).status_code == 404
    # Sigue existiendo para el administrador, y se puede volver a activar.
    assert plan["id"] in [p["id"] for p in client.get("/admin/plans", headers=h).json()["items"]]
    r = client.patch(f"/admin/plans/{plan['id']}", json={"active": True, "reason": MOTIVO}, headers=h)
    assert r.status_code == 200
    assert _cotizar(client, user_token, plan["id"]).status_code == 200
    assert [f.action for f in _bitacora(db, plan["id"])] == [
        "plan.create",
        "plan.update",
        "plan.update",
    ]


def test_un_plan_no_guarda_un_precio_de_referencia(
    client: TestClient, admin_token: str, user_token: str
) -> None:
    """Descartado el 2026-10-09: el unico precio es el que se cobra. Si alguien
    lo manda, se ignora."""
    plan = _crear_plan(client, admin_token, display_price_cents=3_000, display_currency="USD")
    assert "display_price_cents" not in plan and "display_currency" not in plan
    data = _cotizar(client, user_token, plan["id"]).json()
    assert (data["total_cents"], data["currency"]) == (8_000_000, "COP")


def test_un_cambio_de_plan_rechazado_no_deja_fila(client: TestClient, admin_token: str, db) -> None:
    plan = _crear_plan(client, admin_token)
    h = auth(admin_token)
    ruta = f"/admin/plans/{plan['id']}"
    # No cambia nada.
    r = client.patch(ruta, json={"price_cents": 8_000_000, "reason": MOTIVO}, headers=h)
    assert r.status_code == 409
    assert client.patch(ruta, json={"reason": MOTIVO}, headers=h).status_code == 409
    # Sin motivo, o invalido.
    assert client.patch(ruta, json={"price_cents": 1_000}, headers=h).status_code == 422
    assert client.patch(ruta, json={"price_cents": -5, "reason": MOTIVO}, headers=h).status_code == 422
    assert client.patch(ruta, json={"name": None, "reason": MOTIVO}, headers=h).status_code == 422
    assert [f.action for f in _bitacora(db, plan["id"])] == ["plan.create"]
    assert client.patch(
        f"/admin/plans/{uuid.uuid4()}", json={"active": False, "reason": MOTIVO}, headers=h
    ).status_code == 404


def test_el_codigo_y_la_moneda_de_un_plan_no_se_editan(client: TestClient, admin_token: str) -> None:
    plan = _crear_plan(client, admin_token)
    r = client.patch(
        f"/admin/plans/{plan['id']}",
        json={"code": "otro", "currency": "USD", "name": "Otro nombre", "reason": MOTIVO},
        headers=auth(admin_token),
    )
    assert r.status_code == 200
    assert (r.json()["code"], r.json()["currency"]) == (plan["code"], "COP")
    assert r.json()["name"] == "Otro nombre"


# ---------- Cupones ----------


def test_crear_un_cupon_lo_guarda_en_mayusculas_y_deja_fila(
    client: TestClient, admin_token: str, user_token: str, db
) -> None:
    plan = _crear_plan(client, admin_token)
    cupon = _crear_cupon(client, admin_token, code="  bienvenida-" + uuid.uuid4().hex[:6], value=25)
    assert cupon["code"] == cupon["code"].upper().strip()
    assert cupon["code"].startswith("BIENVENIDA-")
    assert (cupon["kind"], cupon["value"], cupon["currency"]) == ("percent", 25, None)
    assert (cupon["redemptions_count"], cupon["plan_ids"], cupon["active"]) == (0, [], True)
    assert cupon["valid_from"] is not None

    data = _cotizar(client, user_token, plan["id"], cupon["code"]).json()
    assert (data["discount_cents"], data["total_cents"]) == (2_000_000, 6_000_000)

    (fila,) = _bitacora(db, cupon["id"])
    assert fila.action == "coupon.create"
    assert fila.after["code"] == cupon["code"]
    assert fila.after["value"] == 25
    assert fila.reason == MOTIVO

    listado = client.get(
        "/admin/coupons", params={"query": cupon["code"].lower()}, headers=auth(admin_token)
    ).json()
    assert [c["id"] for c in listado["items"]] == [cupon["id"]]
    assert listado["total"] == 1


@pytest.mark.parametrize(
    "codigo", ["GANASEGURO", "gana-seguro", "INFALIBLE", "VENTAJA20", "PREDICCION10", "GARANTIZADO"]
)
def test_ningun_codigo_de_cupon_promete_resultados(
    client: TestClient, admin_token: str, codigo: str
) -> None:
    r = client.post("/admin/coupons", json=_cupon_body(code=codigo), headers=auth(admin_token))
    assert r.status_code == 422
    assert "promete resultados" in r.json()["detail"]


@pytest.mark.parametrize(
    "cambios",
    [
        {"value": 100},  # nunca el 100 %
        {"value": 150},
        {"value": 0},
        {"value": 10.5},
        {"currency": "COP"},  # un porcentaje no lleva moneda
        {"kind": "fixed_cents", "value": 500_000},  # monto fijo sin moneda
        {"kind": "fixed_cents", "value": 500_000, "currency": "USD"},  # solo COP
        {"duration": "repeating"},  # sin periodos
        {"duration": "once", "duration_periods": 3},
        {"duration": "forever", "duration_periods": 3},
        {"max_redemptions": 0},
        {"valid_from": "2026-10-10T00:00:00Z", "valid_until": "2026-10-10T00:00:00Z"},
        {"valid_from": "2026-10-10T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"},
        {"plan_ids": [str(uuid.uuid4())]},  # plan que no existe
        {"code": "AB"},
        {"code": "CON ESPACIO"},
        {"reason": "x"},
    ],
)
def test_un_cupon_mal_formado_se_rechaza(client: TestClient, admin_token: str, cambios: dict) -> None:
    r = client.post("/admin/coupons", json=_cupon_body(**cambios), headers=auth(admin_token))
    assert r.status_code == 422, r.text


def test_cupon_del_99_por_ciento_si_se_acepta(client: TestClient, admin_token: str) -> None:
    assert _crear_cupon(client, admin_token, value=99)["value"] == 99


def test_cupon_que_se_repite_y_de_monto_fijo(client: TestClient, admin_token: str) -> None:
    cupon = _crear_cupon(
        client,
        admin_token,
        kind="fixed_cents",
        value=1_000_000,
        currency="COP",
        duration="repeating",
        duration_periods=3,
        max_redemptions=50,
        valid_until=(datetime.now(UTC) + timedelta(days=30)).isoformat(),
    )
    assert (cupon["kind"], cupon["currency"], cupon["duration_periods"]) == ("fixed_cents", "COP", 3)
    assert cupon["max_redemptions"] == 50


def test_el_codigo_de_un_cupon_es_unico_sin_importar_mayusculas(
    client: TestClient, admin_token: str
) -> None:
    cupon = _crear_cupon(client, admin_token)
    r = client.post(
        "/admin/coupons", json=_cupon_body(code=cupon["code"].lower()), headers=auth(admin_token)
    )
    assert r.status_code == 409


def test_desactivar_un_cupon_lo_saca_de_la_cotizacion(
    client: TestClient, admin_token: str, user_token: str, db
) -> None:
    plan = _crear_plan(client, admin_token)
    cupon = _crear_cupon(client, admin_token)
    h = auth(admin_token)
    r = client.patch(
        f"/admin/coupons/{cupon['id']}", json={"active": False, "reason": "Se acabó"}, headers=h
    )
    assert r.status_code == 200 and r.json()["active"] is False
    data = _cotizar(client, user_token, plan["id"], cupon["code"]).json()
    assert (data["coupon"]["reason"], data["total_cents"]) == ("inactive", 8_000_000)

    creado, editado = _bitacora(db, cupon["id"])
    assert editado.action == "coupon.update"
    assert (editado.before["active"], editado.after["active"]) == (True, False)
    assert editado.reason == "Se acabó"

    filtrado = client.get("/admin/coupons", params={"active": "false", "limit": 100}, headers=h)
    assert cupon["id"] in [c["id"] for c in filtrado.json()["items"]]


def test_limitar_un_cupon_a_un_plan(client: TestClient, admin_token: str, user_token: str) -> None:
    uno = _crear_plan(client, admin_token)
    otro = _crear_plan(client, admin_token)
    cupon = _crear_cupon(client, admin_token, plan_ids=[uno["id"]])
    assert cupon["plan_ids"] == [uno["id"]]
    assert _cotizar(client, user_token, otro["id"], cupon["code"]).json()["coupon"]["reason"] == (
        "other_plan"
    )
    r = client.patch(
        f"/admin/coupons/{cupon['id']}",
        json={"plan_ids": [], "reason": MOTIVO},
        headers=auth(admin_token),
    )
    assert r.status_code == 200 and r.json()["plan_ids"] == []
    assert _cotizar(client, user_token, otro["id"], cupon["code"]).json()["coupon"]["applied"] is True


def test_un_cambio_de_cupon_rechazado_no_deja_fila(client: TestClient, admin_token: str, db) -> None:
    cupon = _crear_cupon(client, admin_token)
    h = auth(admin_token)
    ruta = f"/admin/coupons/{cupon['id']}"
    assert client.patch(ruta, json={"value": 10, "reason": MOTIVO}, headers=h).status_code == 409
    assert client.patch(ruta, json={"value": 100, "reason": MOTIVO}, headers=h).status_code == 422
    assert client.patch(ruta, json={"value": 20}, headers=h).status_code == 422
    assert (
        client.patch(ruta, json={"duration": "repeating", "reason": MOTIVO}, headers=h).status_code
        == 422
    )
    assert (
        client.patch(ruta, json={"kind": "fixed_cents", "reason": MOTIVO}, headers=h).status_code
        == 422
    )
    assert [f.action for f in _bitacora(db, cupon["id"])] == ["coupon.create"]
    # Y el cupon quedo como estaba.
    (guardado,) = client.get("/admin/coupons", params={"query": cupon["code"]}, headers=h).json()[
        "items"
    ]
    assert (guardado["kind"], guardado["value"], guardado["duration"]) == ("percent", 10, "once")


def test_el_codigo_de_un_cupon_no_se_edita(client: TestClient, admin_token: str) -> None:
    cupon = _crear_cupon(client, admin_token)
    r = client.patch(
        f"/admin/coupons/{cupon['id']}",
        json={"code": "OTROCODIGO", "value": 30, "reason": MOTIVO},
        headers=auth(admin_token),
    )
    assert r.status_code == 200
    assert (r.json()["code"], r.json()["value"]) == (cupon["code"], 30)


def _redimir(db, cupon_id: str, user_id: str) -> None:
    """Lo que hara el pago aprobado en el paso 5."""
    db.add(CouponRedemption(coupon_id=uuid.UUID(cupon_id), user_id=uuid.UUID(user_id)))
    cupon = db.get(Coupon, uuid.UUID(cupon_id))
    cupon.redemptions_count += 1
    db.commit()


def test_un_cupon_usado_no_cambia_su_descuento_pero_si_se_desactiva(
    client: TestClient, admin_token: str, db
) -> None:
    cupon = _crear_cupon(client, admin_token, max_redemptions=5)
    for _ in range(2):
        cuenta = register_raw(client, f"red-{uuid.uuid4().hex[:10]}@ejemplo.com")
        _redimir(db, cupon["id"], cuenta["user"]["id"])
    h = auth(admin_token)
    ruta = f"/admin/coupons/{cupon['id']}"

    for cambio in ({"value": 50}, {"kind": "fixed_cents", "value": 1_000, "currency": "COP"},
                   {"duration": "forever"}):
        r = client.patch(ruta, json={**cambio, "reason": MOTIVO}, headers=h)
        assert r.status_code == 409, r.text
        assert "ya se usó" in r.json()["detail"]
    # El tope no baja de lo ya usado.
    r = client.patch(ruta, json={"max_redemptions": 1, "reason": MOTIVO}, headers=h)
    assert r.status_code == 422
    # Si se puede ampliar el tope, vencerlo y desactivarlo.
    r = client.patch(ruta, json={"max_redemptions": 10, "active": False, "reason": MOTIVO}, headers=h)
    assert r.status_code == 200, r.text
    assert (r.json()["max_redemptions"], r.json()["active"], r.json()["redemptions_count"]) == (
        10,
        False,
        2,
    )


def test_ver_las_redenciones_de_un_cupon(client: TestClient, admin_token: str, db) -> None:
    cupon = _crear_cupon(client, admin_token)
    correos = [f"red-{uuid.uuid4().hex[:10]}@ejemplo.com" for _ in range(3)]
    for correo in correos:
        _redimir(db, cupon["id"], register_raw(client, correo)["user"]["id"])
    h = auth(admin_token)
    r = client.get(f"/admin/coupons/{cupon['id']}/redemptions", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 3
    assert sorted(i["user_email"] for i in data["items"]) == sorted(correos)
    assert all(i["subscription_id"] is None and i["created_at"] for i in data["items"])

    pagina = client.get(
        f"/admin/coupons/{cupon['id']}/redemptions", params={"limit": 2, "offset": 2}, headers=h
    ).json()
    assert (len(pagina["items"]), pagina["total"]) == (1, 3)

    assert client.get(f"/admin/coupons/{uuid.uuid4()}/redemptions", headers=h).status_code == 404


def test_un_cupon_solo_se_redime_una_vez_por_cuenta(client: TestClient, admin_token: str, db) -> None:
    from sqlalchemy.exc import IntegrityError

    cupon = _crear_cupon(client, admin_token)
    cuenta = register_raw(client, f"red-{uuid.uuid4().hex[:10]}@ejemplo.com")
    _redimir(db, cupon["id"], cuenta["user"]["id"])
    with pytest.raises(IntegrityError):
        _redimir(db, cupon["id"], cuenta["user"]["id"])
    db.rollback()


def test_la_base_no_deja_borrar_un_cupon_con_redenciones(
    client: TestClient, admin_token: str, db
) -> None:
    from sqlalchemy.exc import IntegrityError

    cupon = _crear_cupon(client, admin_token)
    cuenta = register_raw(client, f"red-{uuid.uuid4().hex[:10]}@ejemplo.com")
    _redimir(db, cupon["id"], cuenta["user"]["id"])
    with pytest.raises(IntegrityError):
        db.execute(text("DELETE FROM coupons WHERE id = :id"), {"id": cupon["id"]})
    db.rollback()
