"""Lugares de Siigo y datos de facturacion del comprador (`billing/places.py`,
`billing/billing_profile.py`). Sin base de datos ni red."""

import pytest

from app.billing import places
from app.billing.billing_profile import (
    BillingProfileInput,
    InvalidBillingProfile,
    default_id_type,
    id_types_for,
    validate,
)

BOGOTA = dict(country_code="Co", state_code="11", city_code="11001")
MADRID = dict(country_code="Es", state_code="09", city_code="0101")


def _datos(**cambios: str) -> BillingProfileInput:
    base = dict(
        first_names="María José",
        last_names="Pérez Núñez",
        id_type="13",
        id_number="1.234.567.890",
        address="Cra. 10 # 15-20, apto 301",
        **BOGOTA,
    )
    base.update(cambios)
    return BillingProfileInput(**base)


def _campos(exc: pytest.ExceptionInfo[InvalidBillingProfile]) -> set[str]:
    return {e.field for e in exc.value.errors}


# ---------- Lugares ----------


def test_la_lista_tiene_colombia_completa_y_primero() -> None:
    paises = places.countries()
    assert paises[0].code == "Co" and paises[0].name == "Colombia"
    assert len(places.cities_of("Co")) == 1123
    assert len(paises) == 220


def test_una_ciudad_se_identifica_por_el_trio_y_no_por_su_codigo() -> None:
    # 0101 es Madrid en España y Lisboa en Portugal.
    madrid = places.find("Es", "09", "0101")
    lisboa = places.find("Pt", "01", "0101")
    assert madrid is not None and madrid.city == "Madrid"
    assert lisboa is not None and lisboa.city == "Lisboa"
    assert places.find("Es", "01", "0101") is None


def test_el_codigo_de_pais_se_compara_sin_mayusculas_y_se_devuelve_como_viene() -> None:
    bogota = places.find("CO", "11", "11001")
    assert bogota is not None and bogota.country_code == "Co" and bogota.city == "Bogotá"
    assert places.country("co") is not None and places.is_colombia("CO")


# ---------- Tipos de documento ----------


def test_los_tipos_de_documento_dependen_del_pais() -> None:
    assert id_types_for("Co") == ("13", "22") and default_id_type("Co") == "13"
    assert id_types_for("Es") == ("42", "41", "50") and default_id_type("Es") == "42"


# ---------- Validacion ----------


def test_unos_datos_de_colombia_se_normalizan() -> None:
    datos = validate(_datos(first_names="  María   José ", address="Cra. 10 #  15-20\n apto 301"))
    assert datos.first_names == "María José"
    assert datos.id_number == "1234567890"
    assert datos.address == "Cra. 10 # 15-20 apto 301"
    assert datos.city.city == "Bogotá" and datos.country_code == "Co"


def test_la_cedula_es_numerica_de_3_a_13_digitos() -> None:
    for malo in ("12", "12345678901234", "12A456"):
        with pytest.raises(InvalidBillingProfile) as exc:
            validate(_datos(id_number=malo))
        assert _campos(exc) == {"id_number"}
    assert validate(_datos(id_type="22", id_number="E-1234")).id_number == "E-1234"


def test_un_documento_de_fuera_es_alfanumerico_y_va_en_mayusculas() -> None:
    datos = validate(_datos(id_type="41", id_number="pa 123456", **MADRID))
    assert datos.id_type == "41" and datos.id_number == "PA123456"
    for malo in ("A1", "AB#123", "-AB12", "X" * 21):
        with pytest.raises(InvalidBillingProfile) as exc:
            validate(_datos(id_type="50", id_number=malo, **MADRID))
        assert _campos(exc) == {"id_number"}


def test_un_tipo_que_no_aplica_en_el_pais_se_rechaza() -> None:
    with pytest.raises(InvalidBillingProfile) as exc:
        validate(_datos(id_type="50"))  # NIT de otro pais en Colombia
    assert _campos(exc) == {"id_type"}
    with pytest.raises(InvalidBillingProfile) as exc:
        validate(_datos(id_type="13", **MADRID))  # cedula colombiana fuera
    assert _campos(exc) == {"id_type"}


@pytest.mark.parametrize(
    "nombre", ["", "   ", "Juan2", "Ana_María", "Ana@", "A" * 51, "Juan  -  Pérez!"]
)
def test_un_nombre_raro_se_rechaza(nombre: str) -> None:
    with pytest.raises(InvalidBillingProfile) as exc:
        validate(_datos(first_names=nombre))
    assert _campos(exc) == {"first_names"}


@pytest.mark.parametrize("nombre", ["O'Neil", "Ana-María", "Ñuño", "Jean-Luc", "St. John"])
def test_un_nombre_con_apostrofo_guion_o_punto_vale(nombre: str) -> None:
    assert validate(_datos(last_names=nombre)).last_names == nombre


def test_la_ciudad_tiene_que_estar_en_la_lista_del_pais() -> None:
    with pytest.raises(InvalidBillingProfile) as exc:
        validate(_datos(country_code="Co", state_code="09", city_code="0101"))
    assert _campos(exc) == {"city"}


def test_un_pais_que_no_esta_se_rechaza() -> None:
    with pytest.raises(InvalidBillingProfile) as exc:
        validate(_datos(country_code="Xx"))
    assert "country_code" in _campos(exc)


def test_la_direccion_es_obligatoria_y_tiene_tope() -> None:
    for mala in ("", "  ", "x" * 257):
        with pytest.raises(InvalidBillingProfile) as exc:
            validate(_datos(address=mala))
        assert _campos(exc) == {"address"}


def test_todos_los_errores_salen_juntos() -> None:
    with pytest.raises(InvalidBillingProfile) as exc:
        validate(_datos(first_names="", last_names="", id_number="1", address=""))
    assert _campos(exc) == {"first_names", "last_names", "id_number", "address"}
