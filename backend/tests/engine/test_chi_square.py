"""Prueba chi-cuadrado: senal de sesgo global."""

import pytest

from app.engine.chi_square import MIN_SPINS, P_VALUE_THRESHOLD, chi_square_signal


def _repetir(patron: list[str], veces: int) -> list[str]:
    return (patron * veces)[: len(patron) * veces]


# ---------- Minimo duro de 36 giros ----------


def test_por_debajo_del_minimo_no_se_activa_nunca(europea) -> None:
    """Requisito duro de §2.4: aunque la desviacion sea brutal, con menos de 36
    giros la senal no se activa y no se calcula p-valor."""
    resultados = ["1"] * 35  # todo la misma docena, primera columna, impar, rojo
    r = chi_square_signal(europea, "dozen", resultados)
    assert r.active is False
    assert r.p_value is None
    assert r.statistic is None
    assert "35" in r.reason and str(MIN_SPINS) in r.reason


def test_justo_en_el_minimo_si_evalua(europea) -> None:
    resultados = ["1"] * MIN_SPINS
    r = chi_square_signal(europea, "dozen", resultados)
    assert r.spins_used == MIN_SPINS
    assert r.p_value is not None
    assert r.active is True  # 36 de 36 en la misma docena no es azar


def test_secuencia_vacia(europea) -> None:
    r = chi_square_signal(europea, "dozen", [])
    assert r.active is False
    assert r.p_value is None


# ---------- Comportamiento estadistico ----------


def test_una_muestra_equilibrada_no_activa_la_senal(europea) -> None:
    """Reparto proporcional entre las tres docenas mas el cero: ruido, no sesgo."""
    resultados = _repetir(["1", "13", "25"], 20)  # 60 giros, 20 por docena
    r = chi_square_signal(europea, "dozen", resultados)
    assert r.p_value is not None
    assert r.active is False
    assert "azar" in r.reason


def test_un_sesgo_marcado_si_activa_la_senal(europea) -> None:
    resultados = ["1"] * 40 + ["13"] * 5 + ["25"] * 5
    r = chi_square_signal(europea, "dozen", resultados)
    assert r.active is True
    assert r.p_value < P_VALUE_THRESHOLD
    assert r.degrees_of_freedom == 3  # 3 docenas + la celda del cero, menos 1


def test_la_evidencia_muestra_observado_y_esperado(europea) -> None:
    """§2.4 pide evidencia del tipo 'salio 15 de 40 (37.5%) vs. 32.4% esperado'."""
    resultados = ["1"] * 40 + ["13"] * 5 + ["25"] * 5
    r = chi_square_signal(europea, "dozen", resultados)
    texto = " | ".join(r.evidence)
    assert "de 50" in texto
    assert "esperado" in texto
    assert "32.4%" in texto


def test_categoria_sin_resultados_excluidos_tiene_un_grado_menos(europea) -> None:
    """Color cubre los 37 numeros, asi que no hay celda de 'sin grupo':
    3 grupos - 1 = 2 grados de libertad."""
    r = chi_square_signal(europea, "color", _repetir(["1", "2", "0"], 20))
    assert r.degrees_of_freedom == 2


def test_usa_el_historial_completo_sin_decaimiento(europea) -> None:
    """§2.4: es la unica senal que no aplica recencia. La misma muestra en
    distinto orden debe dar exactamente el mismo p-valor."""
    resultados = ["1"] * 40 + ["13"] * 5 + ["25"] * 5
    invertida = list(reversed(resultados))
    a = chi_square_signal(europea, "dozen", resultados)
    b = chi_square_signal(europea, "dozen", invertida)
    assert a.p_value == pytest.approx(b.p_value)
    assert a.statistic == pytest.approx(b.statistic)


def test_categoria_inexistente_lanza_error(europea) -> None:
    with pytest.raises(KeyError):
        chi_square_signal(europea, "inexistente", ["1"] * 40)


def test_funciona_con_un_juego_que_no_es_ruleta(dados) -> None:
    r = chi_square_signal(dados, "parity", ["2"] * 40)
    assert r.active is True
    assert r.degrees_of_freedom == 1  # par e impar cubren todo: 2 celdas - 1
