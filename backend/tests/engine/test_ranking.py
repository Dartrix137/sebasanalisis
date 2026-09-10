"""Puntaje de significancia, top-3 y fuerza de la senal."""

import pytest

from app.engine.chi_square import all_chi_square_signals, chi_square_signal
from tests.engine.test_chi_square import (
    GIROS_CON_SESGO_BURDO,
    GIROS_SIN_SESGO_CON_UN_P_BAJO,
)
from app.engine.frequency import category_frequencies
from app.engine.ranking import (
    EV_MEDIUM,
    EV_STRONG,
    SignalStrength,
    classify_strength,
    rank_suggestions,
    significance_score,
    top3,
)


# ---------- significance_score ----------


def test_a_igual_desviacion_pesa_mas_la_muestra_grande(europea) -> None:
    """|desviacion| x sqrt(giros ponderados): la raiz del volumen evita que una
    desviacion enorme sobre cuatro giros valga lo mismo que una moderada sobre
    cien (§2.6)."""
    corta = ["1", "3", "5", "7"]
    larga = ["1", "3", "5", "7"] * 25

    f_corta = next(f for f in category_frequencies(europea, "color", corta) if f.group_id == "red")
    f_larga = next(f for f in category_frequencies(europea, "color", larga) if f.group_id == "red")
    assert significance_score(f_larga) > significance_score(f_corta)


def test_sin_desviacion_el_puntaje_es_cero(europea) -> None:
    f = next(f for f in category_frequencies(europea, "color", []) if f.group_id == "red")
    assert significance_score(f) == pytest.approx(0.0)


# ---------- Fuerza de la senal ----------


def test_fuerte_exige_ev_alto_y_respaldo_de_chi_cuadrado(europea) -> None:
    """Interpretacion conservadora de §2.6: sin chi-cuadrado activo, un EV alto
    no basta para llamar FUERTE a una senal."""
    chi_activo = chi_square_signal(europea, "dozen", GIROS_CON_SESGO_BURDO)
    chi_inactivo = chi_square_signal(europea, "dozen", ["1"] * 10)
    assert chi_activo.active and not chi_inactivo.active

    assert classify_strength(EV_STRONG, chi_activo) is SignalStrength.strong
    # Mismo EV, sin respaldo: baja a MEDIA, no se queda en FUERTE.
    assert classify_strength(EV_STRONG, chi_inactivo) is SignalStrength.medium
    assert classify_strength(EV_STRONG, None) is SignalStrength.medium


def test_umbrales_de_media_y_debil(europea) -> None:
    chi = chi_square_signal(europea, "dozen", ["1"] * 10)
    assert classify_strength(EV_MEDIUM, chi) is SignalStrength.medium
    assert classify_strength(EV_MEDIUM - 0.001, chi) is SignalStrength.weak
    assert classify_strength(-0.027, chi) is SignalStrength.weak


def test_una_mesa_normal_no_produce_senales_fuertes(europea) -> None:
    """Con una secuencia sin sesgo real, nada debe salir como FUERTE."""
    resultados = [str(n % 37) for n in range(60)]
    fuertes = [s for s in rank_suggestions(europea, resultados) if s.strength is SignalStrength.strong]
    assert fuertes == []


# ---------- Ranking ----------


def test_devuelve_todas_las_senales_y_marca_solo_tres(europea) -> None:
    """§2.6: las debiles se muestran etiquetadas, nunca se ocultan."""
    sugerencias = rank_suggestions(europea, ["1", "3", "5", "0", "13"])
    total_grupos = sum(len(c.groups) for c in europea.categories)
    assert len(sugerencias) == total_grupos
    assert sum(1 for s in sugerencias if s.is_top3) == 3
    assert len(top3(europea, ["1", "3", "5", "0", "13"])) == 3


def test_estan_ordenadas_por_significancia_descendente(europea) -> None:
    sugerencias = rank_suggestions(europea, ["1", "3", "5", "7", "9", "12"])
    puntajes = [s.significance_score for s in sugerencias]
    assert puntajes == sorted(puntajes, reverse=True)
    # Y las tres marcadas son justamente las tres primeras.
    assert all(s.is_top3 for s in sugerencias[:3])
    assert not any(s.is_top3 for s in sugerencias[3:])


def test_cada_sugerencia_trae_teorica_y_observada(europea) -> None:
    """Regla anti-falacia del jugador: nunca una sin la otra (§2)."""
    for s in rank_suggestions(europea, ["1", "3", "5"]):
        assert 0 < s.theoretical_probability < 1
        assert 0 <= s.observed_frequency_shrunk <= 1
        assert s.deviation == pytest.approx(
            s.observed_frequency_shrunk - s.theoretical_probability
        )
        # Y el EV teorico al lado del observado, para que se vean juntos.
        assert s.ev_theoretical < 0


def test_el_ev_teorico_es_siempre_la_ventaja_de_la_casa(europea) -> None:
    for s in rank_suggestions(europea, ["1", "3", "5"]):
        assert s.ev_theoretical == pytest.approx(-1 / 37, abs=1e-9)


def test_el_pvalue_solo_aparece_si_chi_cuadrado_esta_activo(europea) -> None:
    pocos = rank_suggestions(europea, ["1", "3", "5"])
    assert all(s.chi_square_pvalue_adjusted is None for s in pocos)

    sesgada = rank_suggestions(europea, GIROS_CON_SESGO_BURDO)
    docenas = [s for s in sesgada if s.category_id == "dozen"]
    assert all(s.chi_square_pvalue_adjusted is not None for s in docenas)


def test_el_ranking_expone_el_pvalue_corregido_no_el_crudo(europea) -> None:
    """El numero que llega a la UI tiene que ser el que sostuvo la decision."""
    corregido = all_chi_square_signals(europea, GIROS_CON_SESGO_BURDO)[
        "dozen"
    ].p_value_adjusted

    docenas = [
        s
        for s in rank_suggestions(europea, GIROS_CON_SESGO_BURDO)
        if s.category_id == "dozen"
    ]
    assert all(s.chi_square_pvalue_adjusted == pytest.approx(corregido) for s in docenas)


def test_el_ruido_corregido_no_llega_a_fuerte(europea) -> None:
    """Sin correccion, estas 210 tiradas al azar producian una senal FUERTE."""
    sugerencias = rank_suggestions(europea, GIROS_SIN_SESGO_CON_UN_P_BAJO)
    assert all(s.strength is not SignalStrength.strong for s in sugerencias)
    assert all(s.chi_square_pvalue_adjusted is None for s in sugerencias)


# ---------- Ventana de recencia vs. historial completo ----------


def test_el_chi_cuadrado_usa_el_historial_completo_no_la_ventana(europea) -> None:
    """El recorte por ventana dejaba al chi-cuadrado viendo 50 giros y apagado.

    Con el sesgo burdo entero la senal se activa; si solo se le pasa la ventana
    de recencia, la muestra no llega al minimo y no hay p-valor que mostrar.
    """
    ventana = GIROS_CON_SESGO_BURDO[-50:]

    recortado = rank_suggestions(europea, ventana)
    assert all(s.chi_square_pvalue_adjusted is None for s in recortado)

    completo = rank_suggestions(europea, ventana, full_history=GIROS_CON_SESGO_BURDO)
    docenas = [s for s in completo if s.category_id == "dozen"]
    assert all(s.chi_square_pvalue_adjusted is not None for s in docenas)


def test_la_ventana_no_altera_el_chi_cuadrado(europea) -> None:
    """El chi-cuadrado depende solo del historial completo: cambiar la ventana
    de recencia mueve las frecuencias, nunca el p-valor."""
    a = rank_suggestions(
        europea, GIROS_CON_SESGO_BURDO[-30:], full_history=GIROS_CON_SESGO_BURDO
    )
    b = rank_suggestions(
        europea, GIROS_CON_SESGO_BURDO[-90:], full_history=GIROS_CON_SESGO_BURDO
    )
    por_grupo = {(s.category_id, s.group_id): s.chi_square_pvalue_adjusted for s in a}
    assert all(
        por_grupo[(s.category_id, s.group_id)] == pytest.approx(s.chi_square_pvalue_adjusted)
        for s in b
    )


def test_sin_giros_no_hay_desviacion_en_ninguna_senal(europea) -> None:
    for s in rank_suggestions(europea, []):
        assert s.deviation == pytest.approx(0.0)
        assert s.significance_score == pytest.approx(0.0)


def test_el_orden_es_estable_entre_corridas(europea) -> None:
    resultados = ["1", "3", "5", "0", "13", "24"]
    a = [(s.category_id, s.group_id) for s in rank_suggestions(europea, resultados)]
    b = [(s.category_id, s.group_id) for s in rank_suggestions(europea, resultados)]
    assert a == b


def test_funciona_con_un_juego_que_no_es_ruleta(dados) -> None:
    sugerencias = rank_suggestions(dados, ["2", "4", "6", "3"])
    assert {s.group_id for s in sugerencias} == {"even", "odd"}
