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


#: Sesgo tan burdo que sobrevive a cualquier correccion: sirve para comprobar
#: que el motor no quedo ciego al subir el minimo. No es un sesgo realista —a
#: 220 giros la prueba solo alcanza a ver desviaciones de este tamano.
GIROS_CON_SESGO_BURDO = ["1"] * 180 + ["13"] * 20 + ["25"] * 20


# ---------- Minimo duro de muestra ----------


def test_por_debajo_del_minimo_no_se_activa_nunca(europea) -> None:
    """Requisito duro de §2.4: aunque la desviacion sea brutal, por debajo del
    minimo la senal no se activa y no se calcula p-valor."""
    faltante = MIN_SPINS - 1
    resultados = ["1"] * faltante  # todo la misma docena, columna, impar y rojo
    r = chi_square_signal(europea, "dozen", resultados)
    assert r.active is False
    assert r.p_value is None
    assert r.statistic is None
    assert str(faltante) in r.reason and str(MIN_SPINS) in r.reason


def test_justo_en_el_minimo_si_evalua(europea) -> None:
    resultados = ["1"] * MIN_SPINS
    r = chi_square_signal(europea, "dozen", resultados)
    assert r.spins_used == MIN_SPINS
    assert r.p_value is not None
    assert r.active is True  # todos en la misma docena no es azar


def test_el_minimo_es_un_piso_de_ruido_no_de_deteccion_de_sesgo() -> None:
    """El numero no es arbitrario y su razon de ser tampoco.

    A 200 giros la prueba solo tiene potencia para ver una docena saliendo ~43%
    contra 32.4% teorico; un sesgo explotable (>33.3%) pediria del orden de
    30.000 giros. El minimo existe para que FUERTE no se desbloquee con muestras
    que no sostienen nada, no porque a partir de ahi se detecte sesgo.
    """
    assert MIN_SPINS == 200


def test_secuencia_vacia(europea) -> None:
    r = chi_square_signal(europea, "dozen", [])
    assert r.active is False
    assert r.p_value is None


# ---------- Comportamiento estadistico ----------


def test_una_muestra_equilibrada_no_activa_la_senal(europea) -> None:
    """Reparto proporcional entre las tres docenas mas el cero: ruido, no sesgo."""
    resultados = _repetir(["1", "13", "25"], 70)  # 210 giros, 70 por docena
    r = chi_square_signal(europea, "dozen", resultados)
    assert r.p_value is not None
    assert r.active is False
    assert "azar" in r.reason


def test_un_sesgo_marcado_si_activa_la_senal(europea) -> None:
    r = chi_square_signal(europea, "dozen", GIROS_CON_SESGO_BURDO)
    assert r.active is True
    assert r.p_value < P_VALUE_THRESHOLD
    assert r.degrees_of_freedom == 3  # 3 docenas + la celda del cero, menos 1


def test_la_evidencia_muestra_observado_y_esperado(europea) -> None:
    """§2.4 pide evidencia del tipo 'salio 15 de 40 (37.5%) vs. 32.4% esperado'."""
    r = chi_square_signal(europea, "dozen", GIROS_CON_SESGO_BURDO)
    texto = " | ".join(r.evidence)
    assert f"de {len(GIROS_CON_SESGO_BURDO)}" in texto
    assert "esperado" in texto
    assert "32.4%" in texto


def test_categoria_sin_resultados_excluidos_tiene_un_grado_menos(europea) -> None:
    """Color cubre los 37 numeros, asi que no hay celda de 'sin grupo':
    3 grupos - 1 = 2 grados de libertad."""
    r = chi_square_signal(europea, "color", _repetir(["1", "2", "0"], 70))
    assert r.degrees_of_freedom == 2


def test_usa_el_historial_completo_sin_decaimiento(europea) -> None:
    """§2.4: es la unica senal que no aplica recencia. La misma muestra en
    distinto orden debe dar exactamente el mismo p-valor."""
    invertida = list(reversed(GIROS_CON_SESGO_BURDO))
    a = chi_square_signal(europea, "dozen", GIROS_CON_SESGO_BURDO)
    b = chi_square_signal(europea, "dozen", invertida)
    assert a.p_value == pytest.approx(b.p_value)
    assert a.statistic == pytest.approx(b.statistic)


def test_categoria_inexistente_lanza_error(europea) -> None:
    """El nombre se valida antes que la muestra: es un error de programacion,
    no una senal que no alcanza el minimo."""
    with pytest.raises(KeyError):
        chi_square_signal(europea, "inexistente", ["1"] * 40)


def test_funciona_con_un_juego_que_no_es_ruleta(dados) -> None:
    r = chi_square_signal(dados, "parity", ["2"] * MIN_SPINS)
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


#: 210 giros generados al azar sobre una rueda europea justa (semilla fija), es
#: decir: sin ningun sesgo, por construccion. Aun asi `color` sale con p=0.023,
#: que aislado se activaria como "sesgo global" y desbloquearia la etiqueta
#: FUERTE. Corregido por las cinco pruebas simultaneas queda en q=0.116 y no
#: activa nada, que es lo correcto. Es el caso exacto que motiva la correccion.
GIROS_SIN_SESGO_CON_UN_P_BAJO = (
    "36 2 27 30 36 0 13 29 31 17 10 2 33 31 20 4 15 23 2 26 8 22 24 26 18 16 29 "
    "11 19 23 8 29 15 28 24 2 0 15 8 12 19 34 23 15 20 35 28 27 30 4 20 32 10 14 "
    "26 15 2 2 31 19 4 34 5 9 24 36 23 9 7 6 28 10 12 22 27 26 28 15 17 9 33 11 7 "
    "17 29 19 10 11 11 30 22 20 27 14 0 34 2 21 20 15 5 16 28 25 10 24 31 15 33 "
    "17 33 30 31 4 10 31 29 25 8 26 34 22 34 24 31 10 35 28 6 26 2 0 28 34 4 3 22 "
    "5 9 6 29 31 8 29 27 32 28 21 16 29 27 21 33 33 9 15 20 2 12 36 30 1 7 18 27 "
    "15 18 5 2 35 6 18 10 30 9 23 25 12 22 11 5 12 27 13 6 19 29 33 27 28 35 13 "
    "17 23 7 0 13 27 26 24 12 4 27 5 3 22 16 23 29 27"
).split()


def test_ruido_con_p_bajo_no_sobrevive_a_la_familia(europea) -> None:
    """Regresion del defecto que la correccion arregla."""
    sola = chi_square_signal(europea, "color", GIROS_SIN_SESGO_CON_UN_P_BAJO)
    assert sola.p_value < P_VALUE_THRESHOLD
    assert sola.active is True  # aislada, se activaria

    familia = all_chi_square_signals(europea, GIROS_SIN_SESGO_CON_UN_P_BAJO)
    assert familia["color"].p_value == pytest.approx(sola.p_value)
    assert familia["color"].p_value_adjusted > P_VALUE_THRESHOLD
    assert familia["color"].active is False
    assert not any(r.active for r in familia.values())


def test_el_motivo_explica_que_fue_la_correccion_y_no_el_p_crudo(europea) -> None:
    """Ver una senal apagada junto a p=0.023 parece un error de calculo desde
    fuera. El motivo tiene que decir que la apago la familia, no el azar."""
    motivo = all_chi_square_signals(europea, GIROS_SIN_SESGO_CON_UN_P_BAJO)["color"].reason
    assert "5 pruebas" in motivo
    assert "0.023" in motivo  # el p crudo sigue a la vista
    assert "corregido" in motivo


def test_un_sesgo_real_si_sobrevive_a_la_correccion(europea) -> None:
    """La correccion no puede volver el motor ciego: un sesgo marcado sigue activo."""
    familia = all_chi_square_signals(europea, GIROS_CON_SESGO_BURDO)
    assert familia["dozen"].active is True
    assert familia["dozen"].p_value_adjusted < P_VALUE_THRESHOLD


def test_las_categorias_sin_muestra_no_entran_en_la_familia(europea) -> None:
    """Contarlas inflaria m y castigaria a las demas sin haber mirado nada."""
    familia = all_chi_square_signals(europea, ["1"] * 10)
    assert all(r.p_value is None for r in familia.values())
    assert all(r.p_value_adjusted is None for r in familia.values())
    assert all(r.active is False for r in familia.values())


def test_el_ajustado_nunca_es_menor_que_el_crudo(europea) -> None:
    familia = all_chi_square_signals(europea, GIROS_SIN_SESGO_CON_UN_P_BAJO)
    evaluadas = [r for r in familia.values() if r.p_value is not None]
    assert len(evaluadas) == 5
    assert all(r.p_value_adjusted >= r.p_value for r in evaluadas)


def test_activa_implica_ajustado_bajo_el_umbral(europea) -> None:
    """Invariante que amarra la decision al valor corregido, nunca al crudo."""
    for giros in (GIROS_SIN_SESGO_CON_UN_P_BAJO, GIROS_CON_SESGO_BURDO):
        for r in all_chi_square_signals(europea, giros).values():
            if r.active:
                assert r.p_value_adjusted < P_VALUE_THRESHOLD
