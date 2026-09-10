"""Auto-evaluacion contra la linea base ingenua (§2.7)."""

import random

import pytest

from app.engine.baseline import (
    VERDICT_NO_DATA,
    evaluate,
    matches,
    naive_baseline_choice,
)
from app.engine.ranking import Suggestion, SignalStrength


def _sugerencia(category_id: str, group_id: str) -> Suggestion:
    return Suggestion(
        category_id=category_id,
        group_id=group_id,
        group_label=group_id,
        theoretical_probability=0.5,
        observed_frequency_shrunk=0.5,
        deviation=0.0,
        significance_score=0.0,
        strength=SignalStrength.weak,
        ev=0.0,
        ev_theoretical=0.0,
        chi_square_pvalue_adjusted=None,
        payout=1,
        raw_count=0,
        raw_total=0,
        is_top3=True,
    )


# ---------- Linea base ingenua ----------


def test_repite_el_grupo_del_ultimo_resultado(europea) -> None:
    assert naive_baseline_choice(europea, "color", ["2", "4", "1"]) == "red"
    assert naive_baseline_choice(europea, "color", ["1", "3", "2"]) == "black"
    assert naive_baseline_choice(europea, "dozen", ["1", "13"]) == "second"


def test_sin_giros_no_elige_nada(europea) -> None:
    assert naive_baseline_choice(europea, "color", []) is None


def test_si_el_ultimo_no_cae_en_ningun_grupo_no_elige(europea) -> None:
    """El 0 no pertenece a ninguna docena, asi que la linea base se abstiene."""
    assert naive_baseline_choice(europea, "dozen", ["1", "13", "0"]) is None
    # Pero en color si, porque el 0 es verde.
    assert naive_baseline_choice(europea, "color", ["1", "0"]) == "green"


# ---------- Coincidencias ----------


def test_coincidencia_de_una_sugerencia(europea) -> None:
    s = _sugerencia("color", "red")
    assert matches(europea, s, "1") is True   # 1 es rojo
    assert matches(europea, s, "2") is False  # 2 es negro
    assert matches(europea, s, "0") is False  # 0 es verde


# ---------- Informe ----------


def test_sin_historial_suficiente_el_veredicto_lo_dice(europea) -> None:
    informe = evaluate(europea, [])
    assert informe.total_suggestions == 0
    assert informe.verdict == VERDICT_NO_DATA


def test_el_informe_compara_motor_y_linea_base(europea) -> None:
    resultados = ["1", "3", "5", "2", "4", "0", "13", "24", "7", "9"]
    informe = evaluate(europea, resultados)

    assert informe.total_suggestions > 0
    assert informe.baseline_suggestions > 0
    assert 0 <= informe.match_rate <= 1
    assert 0 <= informe.baseline_match_rate <= 1
    assert informe.match_rate == pytest.approx(
        informe.matched_suggestions / informe.total_suggestions
    )
    assert informe.baseline_match_rate == pytest.approx(
        informe.baseline_matched / informe.baseline_suggestions
    )


def test_el_veredicto_nunca_promete_resultados_futuros(europea) -> None:
    """El copy de §2.7 es la barrera de honestidad del producto."""
    resultados = [str(random.Random(7).randint(0, 36)) for _ in range(40)]
    veredicto = evaluate(europea, resultados).verdict.lower()

    for prohibida in ("predic", "va a salir", "acierto", "precision", "garantiz"):
        assert prohibida not in veredicto, f"el veredicto usa '{prohibida}'"


def test_no_usa_el_resultado_que_esta_evaluando(europea) -> None:
    """La re-simulacion solo puede mirar los giros anteriores a cada paso.

    Si mirara el resultado que evalua, agregar giros al final cambiaria las
    coincidencias ya contadas de los giros anteriores.
    """
    base = ["1", "3", "5", "2", "4", "0", "13"]
    corto = evaluate(europea, base)
    largo = evaluate(europea, base + ["24", "7"])
    assert largo.matched_suggestions >= corto.matched_suggestions
    assert largo.total_suggestions > corto.total_suggestions


def test_es_una_funcion_pura(europea) -> None:
    resultados = ["1", "3", "5", "2", "4"]
    copia = list(resultados)
    a = evaluate(europea, resultados)
    b = evaluate(europea, resultados)
    assert a == b
    assert resultados == copia


def test_funciona_con_un_juego_que_no_es_ruleta(dados) -> None:
    informe = evaluate(dados, ["2", "3", "4", "5", "6"])
    assert informe.total_suggestions > 0
