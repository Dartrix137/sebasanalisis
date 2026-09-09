"""Shrinkage bayesiano y ponderacion por recencia."""

import pytest

from app.engine.frequency import (
    RECENCY_LAMBDA,
    category_frequencies,
    recency_weights,
    shrinkage_estimate,
)


# ---------- Caso de regresion de la skill ----------


def test_shrinkage_caso_de_referencia() -> None:
    """p = (7 + 8 x 0.4865) / (11 + 8) = 10.892 / 19 ~= 0.5733.

    Si diera 0.636 (7/11) significaria que el shrinkage no se esta aplicando.
    """
    resultado = shrinkage_estimate(favorable=7, total=11, p_teorica=0.4865, alpha=8)
    assert resultado == pytest.approx(0.573, abs=0.001)
    assert resultado != pytest.approx(7 / 11, abs=0.001)


def test_shrinkage_con_muestra_vacia_devuelve_la_teorica() -> None:
    """Sin datos, la lectura prudente es la probabilidad teorica."""
    assert shrinkage_estimate(0, 0, 0.4865, 8) == pytest.approx(0.4865)


def test_shrinkage_con_alpha_cero_es_la_frecuencia_cruda() -> None:
    assert shrinkage_estimate(7, 11, 0.4865, 0) == pytest.approx(7 / 11)


def test_shrinkage_se_acerca_a_la_cruda_con_mucho_volumen() -> None:
    """Con pocos datos queda cerca de la teorica; con muchos, de lo observado."""
    poco = shrinkage_estimate(3, 4, 0.4865, 8)
    mucho = shrinkage_estimate(750, 1000, 0.4865, 8)
    assert abs(poco - 0.4865) < abs(poco - 0.75)
    assert mucho == pytest.approx(0.75, abs=0.01)


def test_shrinkage_rechaza_valores_invalidos() -> None:
    with pytest.raises(ValueError):
        shrinkage_estimate(1, 2, 0.5, alpha=-1)
    with pytest.raises(ValueError):
        shrinkage_estimate(-1, 2, 0.5, alpha=8)


# ---------- Recencia ----------


def test_el_mas_reciente_pesa_uno_y_el_peso_decae_hacia_atras() -> None:
    pesos = recency_weights(5)
    assert pesos[-1] == pytest.approx(1.0)
    assert pesos == sorted(pesos), "el peso debe crecer hacia el final de la lista"
    assert pesos[-2] == pytest.approx(RECENCY_LAMBDA)
    assert pesos[0] == pytest.approx(RECENCY_LAMBDA**4)


def test_vida_media_alrededor_de_22_tiradas() -> None:
    """lambda = 0.969 da una vida media de ~22 giros (§2.3)."""
    assert RECENCY_LAMBDA**22 == pytest.approx(0.5, abs=0.01)


def test_lista_vacia_no_rompe() -> None:
    assert recency_weights(0) == []


def test_la_recencia_da_mas_peso_a_lo_reciente(europea) -> None:
    """Misma cantidad de rojos y negros, pero los rojos son recientes."""
    resultados = ["2", "4", "6", "8", "1", "3", "5", "7"]  # 4 negros luego 4 rojos
    freq = {f.group_id: f for f in category_frequencies(europea, "color", resultados)}
    assert freq["red"].observed_frequency_shrunk > freq["black"].observed_frequency_shrunk


def test_sin_decaimiento_ambos_quedan_iguales(europea) -> None:
    resultados = ["2", "4", "6", "8", "1", "3", "5", "7"]
    freq = {
        f.group_id: f
        for f in category_frequencies(europea, "color", resultados, lambda_=1.0)
    }
    assert freq["red"].observed_frequency_shrunk == pytest.approx(
        freq["black"].observed_frequency_shrunk
    )


# ---------- Regla anti-falacia del jugador ----------


def test_siempre_devuelve_la_teorica_junto_a_la_observada(europea) -> None:
    """§2: nunca se muestra una sin la otra."""
    for f in category_frequencies(europea, "dozen", ["1", "13", "25", "7"]):
        assert f.theoretical_probability == pytest.approx(12 / 37, abs=0.0001)
        assert 0 <= f.observed_frequency_shrunk <= 1
        assert f.deviation == pytest.approx(
            f.observed_frequency_shrunk - f.theoretical_probability
        )


def test_el_denominador_incluye_los_ceros(europea) -> None:
    """La teorica de una docena es 12/37 contando el 0, asi que la observada
    tambien debe contarlo. Excluirlo inflaria toda docena por encima de su
    teorica y haria la comparacion deshonesta."""
    resultados = ["1", "2", "3", "0", "0", "0"]
    freq = {f.group_id: f for f in category_frequencies(europea, "dozen", resultados)}
    assert freq["first"].raw_total == 6
    assert freq["first"].raw_count == 3
    # Sin ceros en el denominador la cruda seria 1.0; con ellos, 0.5.
    assert freq["first"].raw_weighted_frequency < 1.0


def test_sin_giros_todas_las_frecuencias_son_la_teorica(europea) -> None:
    for f in category_frequencies(europea, "color", []):
        assert f.observed_frequency_shrunk == pytest.approx(f.theoretical_probability)
        assert f.deviation == pytest.approx(0.0)


def test_categoria_inexistente_lanza_error(europea) -> None:
    with pytest.raises(KeyError):
        category_frequencies(europea, "inexistente", ["1"])


def test_es_una_funcion_pura(europea) -> None:
    resultados = ["1", "2", "3", "0"]
    copia = list(resultados)
    a = category_frequencies(europea, "color", resultados)
    b = category_frequencies(europea, "color", resultados)
    assert [x.observed_frequency_shrunk for x in a] == [x.observed_frequency_shrunk for x in b]
    assert resultados == copia, "no debe mutar su entrada"
