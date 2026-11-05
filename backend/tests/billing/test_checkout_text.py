"""Los textos del producto que viajan a Tipster Page, en ASCII (paso 5.3)."""

import pytest

from app.billing.checkout_text import ascii_text, product_description, product_name


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Acceso Mensual", "Acceso Mensual"),
        ("Acceso Bimestral", "Acceso Bimestral"),
        ("Suscripción Señal", "Suscripcion Senal"),
        ("  dos   espacios ", "dos espacios"),
        ("Plan ☆ especial — ruleta", "Plan especial ruleta"),
        ("Ünïcödé", "Unicode"),
    ],
)
def test_ascii_text(texto: str, esperado: str) -> None:
    assert ascii_text(texto) == esperado
    assert ascii_text(texto).isascii()


def test_un_texto_que_queda_vacio_es_un_error() -> None:
    with pytest.raises(ValueError):
        ascii_text("☆☆☆")


def test_el_largo_se_corta() -> None:
    assert len(ascii_text("a" * 500)) == 100


def test_el_nombre_del_producto_es_el_del_plan_en_ascii() -> None:
    assert product_name("Acceso Mensual") == "Acceso Mensual"


@pytest.mark.parametrize(
    ("intervalo", "cantidad", "esperado"),
    [
        ("month", 1, "Sebasanalisis: acceso por 1 mes"),
        ("month", 2, "Sebasanalisis: acceso por 2 meses"),
        ("year", 1, "Sebasanalisis: acceso por 12 meses"),
    ],
)
def test_la_descripcion_dice_el_periodo(intervalo: str, cantidad: int, esperado: str) -> None:
    assert product_description(intervalo, cantidad) == esperado


@pytest.mark.parametrize(("intervalo", "cantidad"), [("week", 1), ("month", 0)])
def test_un_periodo_invalido_es_un_error(intervalo: str, cantidad: int) -> None:
    with pytest.raises(ValueError):
        product_description(intervalo, cantidad)
