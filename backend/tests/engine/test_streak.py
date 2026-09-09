"""Racha activa y cola binomial."""

import pytest

from app.engine.streak import active_streak, longest_active_streak, streak_probability


# ---------- Tabla de regresion de la skill (europea, p = 18/37) ----------


@pytest.mark.parametrize(
    ("n", "esperada"),
    [(2, 0.2367), (3, 0.1152), (4, 0.0560), (5, 0.0273), (6, 0.0133)],
)
def test_probabilidad_de_racha(n, esperada) -> None:
    assert streak_probability(n, 18 / 37) == pytest.approx(esperada, abs=0.0005)


def test_racha_de_cero_es_certeza() -> None:
    assert streak_probability(0, 18 / 37) == 1.0


def test_rechaza_entradas_invalidas() -> None:
    with pytest.raises(ValueError):
        streak_probability(-1, 0.5)
    with pytest.raises(ValueError):
        streak_probability(3, 1.5)


# ---------- Racha activa ----------


def test_cuenta_la_racha_al_final_de_la_secuencia(europea) -> None:
    # 1, 3, 5 son rojos; 2 es negro.
    racha = active_streak(europea, "color", ["2", "1", "3", "5"])
    assert racha.group_id == "red"
    assert racha.consecutive_count == 3
    assert racha.probability_of_streak == pytest.approx((18 / 37) ** 3, abs=1e-9)


def test_la_probabilidad_del_proximo_giro_no_cambia_por_la_racha(europea) -> None:
    """El punto entero de §2.5: la racha describe lo que ya paso."""
    corta = active_streak(europea, "color", ["1", "3"])
    larga = active_streak(europea, "color", ["1", "3", "5", "7", "9", "12", "14"])
    assert corta.theoretical_probability_next == larga.theoretical_probability_next
    assert larga.theoretical_probability_next == pytest.approx(18 / 37, abs=0.0001)
    # Y la probabilidad de la racha si cae al alargarse.
    assert larga.probability_of_streak < corta.probability_of_streak


def test_el_cero_corta_la_racha_de_paridad(europea) -> None:
    """El 0 no es par ni impar, asi que rompe la racha en vez de continuarla."""
    assert active_streak(europea, "parity", ["2", "4", "6", "0"]) is None
    racha = active_streak(europea, "parity", ["0", "2", "4", "6"])
    assert racha.consecutive_count == 3


def test_el_cero_si_continua_la_racha_de_color(europea) -> None:
    """En color el 0 si tiene grupo propio: verde."""
    racha = active_streak(europea, "color", ["1", "0", "0"])
    assert racha.group_id == "green"
    assert racha.consecutive_count == 2


def test_secuencia_vacia(europea) -> None:
    assert active_streak(europea, "color", []) is None


def test_un_solo_giro_es_racha_de_uno(europea) -> None:
    assert active_streak(europea, "color", ["1"]).consecutive_count == 1


def test_la_racha_mas_larga_entre_categorias(europea) -> None:
    """1, 2, 4 y 6 son negros/pares solo en parte, pero los cuatro caen en la
    primera docena: la racha mas larga es esa, de 4, no la de color, de 3."""
    racha = longest_active_streak(europea, ["1", "2", "4", "6"])
    assert racha is not None
    assert racha.category_id == "dozen"
    assert racha.consecutive_count == 4

    # Y la de color, mirada por separado, es de 3 (2, 4, 6 negros tras el 1 rojo).
    assert active_streak(europea, "color", ["1", "2", "4", "6"]).consecutive_count == 3


def test_sin_racha_relevante_devuelve_none(europea) -> None:
    """Con min_length=2, un unico giro no cuenta como racha."""
    assert longest_active_streak(europea, ["1"], min_length=2) is None


def test_funciona_con_un_juego_que_no_es_ruleta(dados) -> None:
    racha = active_streak(dados, "parity", ["3", "2", "4"])
    assert racha.group_id == "even"
    assert racha.consecutive_count == 2
