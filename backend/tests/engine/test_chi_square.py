"""Prueba chi-cuadrado: senal de sesgo global."""

import pytest

from app.engine.chi_square import (
    MIN_SPINS,
    P_VALUE_THRESHOLD,
    all_chi_square_signals,
    benjamini_hochberg,
    chi_square_signal,
)


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


# ---------- Correccion por comparaciones multiples (Benjamini-Hochberg) ----------


def test_bh_con_una_sola_prueba_no_corrige_nada() -> None:
    """Familia de tamano 1: no hay comparaciones multiples que corregir."""
    assert benjamini_hochberg([0.04]) == pytest.approx([0.04])


def test_bh_apaga_un_p_de_004_cuando_esta_solo_entre_cinco_pruebas() -> None:
    """El caso que motiva toda la correccion.

    Un p=0.04 aislado se activaria; acompanado de otras cuatro pruebas sin nada
    que mostrar, su q sube a 0.20 y deja de ser significativo. Es correcto: con
    cinco pruebas a 0.05 cada una, ver un 0.04 por azar es lo esperable.
    """
    q = benjamini_hochberg([0.04, 0.5, 0.6, 0.7, 0.8])
    assert q[0] == pytest.approx(0.20)
    assert q[0] > P_VALUE_THRESHOLD


def test_bh_conserva_el_orden_de_entrada() -> None:
    """Los q vuelven alineados con sus p, no reordenados por magnitud."""
    p = [0.8, 0.001, 0.5]
    q = benjamini_hochberg(p)
    assert q[1] < q[2] <= q[0]


def test_bh_nunca_devuelve_mas_de_1_ni_afloja_un_p() -> None:
    p = [0.9, 0.95, 0.99]
    q = benjamini_hochberg(p)
    assert all(v <= 1.0 for v in q)
    # Corregir solo puede endurecer: ningun q queda por debajo de su p.
    assert all(qi >= pi for qi, pi in zip(q, p))


def test_bh_es_monotono_respecto_al_orden_de_los_p() -> None:
    p = [0.001, 0.008, 0.039, 0.041, 0.042]
    q = benjamini_hochberg(p)
    assert q == sorted(q)


def test_bh_familia_vacia() -> None:
    assert benjamini_hochberg([]) == []


#: 80 giros generados al azar sobre una rueda europea justa (semilla fija). Sin
#: correccion, `dozen` (p=0.022) y `high_low` (p=0.025) se activarian como sesgo
#: y desbloquearian la etiqueta FUERTE. No hay ningun sesgo: es ruido de correr
#: cinco pruebas a la vez, que es justo lo que la correccion existe para atrapar.
GIROS_SIN_SESGO_CON_DOS_P_BAJOS = [
    "4", "5", "8", "9", "2", "5", "34", "25", "33", "17", "33", "15", "13", "26",
    "17", "28", "31", "22", "5", "20", "7", "31", "21", "12", "15", "1", "17", "7",
    "14", "23", "10", "21", "27", "3", "6", "9", "14", "2", "36", "34", "4", "1",
    "7", "12", "36", "7", "25", "5", "23", "7", "2", "1", "12", "11", "7", "30",
    "13", "3", "1", "34", "27", "6", "16", "4", "14", "4", "19", "22", "27", "11",
    "3", "32", "29", "2", "6", "25", "12", "16", "22", "30",
]


def test_ruido_con_p_bajo_no_sobrevive_a_la_familia(europea) -> None:
    """Regresion del defecto que la correccion arregla."""
    sola = chi_square_signal(europea, "dozen", GIROS_SIN_SESGO_CON_DOS_P_BAJOS)
    assert sola.p_value < P_VALUE_THRESHOLD
    assert sola.active is True  # aislada, se activaria

    familia = all_chi_square_signals(europea, GIROS_SIN_SESGO_CON_DOS_P_BAJOS)
    assert familia["dozen"].p_value == pytest.approx(sola.p_value)
    assert familia["dozen"].p_value_adjusted > P_VALUE_THRESHOLD
    assert familia["dozen"].active is False
    assert familia["high_low"].active is False


def test_el_motivo_explica_que_fue_la_correccion_y_no_el_p_crudo(europea) -> None:
    """Ver una senal apagada junto a p=0.022 parece un error de calculo desde
    fuera. El motivo tiene que decir que la apago la familia, no el azar."""
    familia = all_chi_square_signals(europea, GIROS_SIN_SESGO_CON_DOS_P_BAJOS)
    motivo = familia["dozen"].reason
    assert "5 pruebas" in motivo
    assert "0.022" in motivo  # el p crudo sigue a la vista
    assert "corregido" in motivo


def test_un_sesgo_real_si_sobrevive_a_la_correccion(europea) -> None:
    """La correccion no puede volver el motor ciego: un sesgo marcado sigue activo."""
    familia = all_chi_square_signals(europea, ["1"] * 40 + ["13"] * 5 + ["25"] * 5)
    assert familia["dozen"].active is True
    assert familia["dozen"].p_value_adjusted < P_VALUE_THRESHOLD


def test_las_categorias_sin_muestra_no_entran_en_la_familia(europea) -> None:
    """Contarlas inflaria m y castigaria a las demas sin haber mirado nada."""
    familia = all_chi_square_signals(europea, ["1"] * 10)
    assert all(r.p_value is None for r in familia.values())
    assert all(r.p_value_adjusted is None for r in familia.values())
    assert all(r.active is False for r in familia.values())


def test_el_ajustado_nunca_es_menor_que_el_crudo(europea) -> None:
    familia = all_chi_square_signals(europea, GIROS_SIN_SESGO_CON_DOS_P_BAJOS)
    evaluadas = [r for r in familia.values() if r.p_value is not None]
    assert len(evaluadas) == 5
    assert all(r.p_value_adjusted >= r.p_value for r in evaluadas)


def test_activa_implica_ajustado_bajo_el_umbral(europea) -> None:
    """Invariante que amarra la decision al valor corregido, nunca al crudo."""
    for giros in (GIROS_SIN_SESGO_CON_DOS_P_BAJOS, ["1"] * 40 + ["13"] * 5 + ["25"] * 5):
        for r in all_chi_square_signals(europea, giros).values():
            if r.active:
                assert r.p_value_adjusted < P_VALUE_THRESHOLD
