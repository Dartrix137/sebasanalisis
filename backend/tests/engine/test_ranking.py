"""Puntaje de significancia, top-3 y fuerza de la senal."""

import pytest

from app.engine.chi_square import chi_square_signal
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
    chi_activo = chi_square_signal(europea, "dozen", ["1"] * 40 + ["13"] * 5 + ["25"] * 5)
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
    assert all(s.chi_square_pvalue is None for s in pocos)

    sesgada = rank_suggestions(europea, ["1"] * 40 + ["13"] * 5 + ["25"] * 5)
    docenas = [s for s in sesgada if s.category_id == "dozen"]
    assert all(s.chi_square_pvalue is not None for s in docenas)


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
