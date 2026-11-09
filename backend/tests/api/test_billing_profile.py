"""Los datos de facturacion del comprador (`/billing/profile`, `/billing/places`;
docs/PLATAFORMA_COMPLETA.md §3.17, "Paso 5.4", punto 8).

Todos los datos son inventados: la empresa de pruebas de Siigo es compartida.
"""

from sqlalchemy import select, text

from app.models import BillingProfile
from tests.api.conftest import auth
from tests.api.test_billing import _mensual
from tests.api.test_subscriptions import _cuenta, _pagos, _suscribir

DATOS = {
    "first_names": "  María   José ",
    "last_names": "Pérez Núñez",
    "country_code": "Co",
    "id_type": "13",
    "id_number": "1.234.567.890",
    "address": "Cra. 10 # 15-20",
    "state_code": "11",
    "city_code": "11001",
}


def test_sin_datos_la_cuenta_no_tiene_y_puede_guardarlos(client, db) -> None:
    token, user_id, _ = _cuenta(client, db, facturacion=False)
    r = client.get("/billing/profile", headers=auth(token))
    assert r.status_code == 200 and r.json() is None

    r = client.put("/billing/profile", json=DATOS, headers=auth(token))
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["first_names"] == "María José" and datos["id_number"] == "1234567890"
    assert datos["id_type"] == "13" and datos["id_type_name"] == "Cédula de ciudadanía"
    assert (datos["country"], datos["state"], datos["city"]) == ("Colombia", "Bogotá D.C", "Bogotá")
    assert client.get("/billing/profile", headers=auth(token)).json()["city_code"] == "11001"


def test_guardar_otra_vez_reemplaza_los_datos(client, db) -> None:
    token, user_id, _ = _cuenta(client, db, facturacion=False)
    client.put("/billing/profile", json=DATOS, headers=auth(token))
    madrid = {**DATOS, "country_code": "Es", "id_type": "41", "id_number": "pa123456",
              "state_code": "09", "city_code": "0101", "address": "Calle Mayor 1"}
    r = client.put("/billing/profile", json=madrid, headers=auth(token))
    assert r.status_code == 200, r.text
    assert (r.json()["city"], r.json()["id_number"], r.json()["id_type_name"]) == (
        "Madrid", "PA123456", "Pasaporte"
    )
    filas = db.scalars(select(BillingProfile).where(BillingProfile.user_id == user_id)).all()
    assert len(filas) == 1


def test_unos_datos_invalidos_responden_422_con_cada_campo(client, db) -> None:
    token, _, _ = _cuenta(client, db, facturacion=False)
    malos = {**DATOS, "first_names": "Juan2", "id_type": "50", "city_code": "99999"}
    r = client.put("/billing/profile", json=malos, headers=auth(token))
    assert r.status_code == 422
    detalle = r.json()["detail"]
    assert detalle["code"] == "invalid_billing_profile"
    assert {e["field"] for e in detalle["errors"]} == {"first_names", "id_type", "city"}
    assert client.get("/billing/profile", headers=auth(token)).json() is None


def test_la_lista_de_paises_trae_los_tipos_de_documento(client, db) -> None:
    token, _, _ = _cuenta(client, db)
    paises = client.get("/billing/places/countries", headers=auth(token)).json()
    assert paises[0]["code"] == "Co" and paises[0]["default_id_type"] == "13"
    assert [t["code"] for t in paises[0]["id_types"]] == ["13", "22"]
    espana = next(p for p in paises if p["code"] == "Es")
    assert espana["default_id_type"] == "50"
    assert [t["name"] for t in espana["id_types"]] == [
        "NIT de otro país", "Pasaporte", "Documento de identificación extranjero"
    ]


def test_las_ciudades_de_un_pais(client, db) -> None:
    token, _, _ = _cuenta(client, db)
    ciudades = client.get("/billing/places/cities?country=Co", headers=auth(token)).json()
    assert len(ciudades) == 1123
    assert {"state_code": "11", "state": "Bogotá D.C", "city_code": "11001", "city": "Bogotá"} in ciudades
    r = client.get("/billing/places/cities?country=Xx", headers=auth(token))
    assert r.status_code == 404


def test_sin_datos_de_facturacion_no_se_abre_un_pago(client, db, tipster) -> None:
    token, user_id, _ = _cuenta(client, db, facturacion=False)
    r = _suscribir(client, token, _mensual(db).id)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "billing_profile_required"
    assert _pagos(db, user_id) == [] and tipster.pedidos == []

    client.put("/billing/profile", json=DATOS, headers=auth(token))
    assert _suscribir(client, token, _mensual(db).id).status_code == 202


def test_la_exportacion_trae_los_datos_y_eliminar_la_cuenta_los_borra(client, db) -> None:
    token, user_id, _ = _cuenta(client, db, facturacion=False)
    client.put("/billing/profile", json=DATOS, headers=auth(token))
    exportado = client.get("/auth/me/export", headers=auth(token)).json()
    assert exportado["billing_profile"]["id_number"] == "1234567890"

    r = client.request("DELETE", "/auth/me", json={"password": "clave-segura-123"},
                       headers=auth(token))
    assert r.status_code == 204, r.text
    quedan = db.execute(text("SELECT count(*) FROM billing_profiles WHERE user_id = :id"),
                        {"id": user_id}).scalar()
    assert quedan == 0
