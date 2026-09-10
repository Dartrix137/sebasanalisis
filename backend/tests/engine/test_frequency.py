"""Shrinkage bayesiano y ponderacion por recencia."""

import pytest

from app.engine.frequency import (
    RECENCY_LAMBDA,
    category_frequencies,
    recency_weights,
    shrinkage_estimate,
    wilson_interval,
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


# ---------- Intervalo de Wilson (§2.2) ----------


def test_wilson_caso_de_referencia_publicado() -> None:
    """0 de 10 al 95% da [0, 0.2775], el valor tabulado de Wilson."""
    bajo, alto = wilson_interval(0, 10)
    assert bajo == pytest.approx(0.0)
    assert alto == pytest.approx(0.2775, abs=0.0001)


def test_wilson_no_colapsa_cuando_el_grupo_nunca_salio() -> None:
    """Es la razon de usar Wilson y no la aproximacion normal.

    Con p=0 la normal da p +- z*raiz(0/n) = [0, 0]: afirmaria certeza absoluta
    de que ese grupo no puede salir, a partir de no haberlo visto. Wilson deja
    el intervalo abierto, que es lo que los datos realmente sostienen.
    """
    bajo, alto = wilson_interval(0, 20)
    assert bajo == 0.0
    assert alto > 0.15


def test_wilson_nunca_se_sale_de_cero_uno() -> None:
    """La otra rotura de la aproximacion normal: limites imposibles."""
    for favorable, total in [(0, 5), (5, 5), (1, 3), (99, 100)]:
        bajo, alto = wilson_interval(favorable, total)
        assert 0.0 <= bajo <= alto <= 1.0


def test_wilson_se_estrecha_con_el_volumen() -> None:
    """El punto de todo el intervalo: 6 de 10 y 600 de 1000 son ambos 60% y no
    dicen lo mismo. Sin esto, una desviacion de ruido y una respaldada por
    volumen se muestran identicas."""
    anchos = []
    for favorable, total in [(6, 10), (60, 100), (600, 1000)]:
        bajo, alto = wilson_interval(favorable, total)
        assert bajo <= favorable / total <= alto
        anchos.append(alto - bajo)

    assert anchos == sorted(anchos, reverse=True)
    # Con cien veces mas giros el intervalo es casi diez veces mas angosto.
    assert anchos[0] / anchos[2] > 8


def test_wilson_es_simetrico_frente_al_complemento() -> None:
    """El intervalo de k/n y el de (n-k)/n son imagen especular."""
    bajo_a, alto_a = wilson_interval(3, 10)
    bajo_b, alto_b = wilson_interval(7, 10)
    assert bajo_a == pytest.approx(1 - alto_b)
    assert alto_a == pytest.approx(1 - bajo_b)


def test_wilson_sin_giros_no_afirma_nada() -> None:
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_wilson_rechaza_conteos_imposibles() -> None:
    with pytest.raises(ValueError):
        wilson_interval(5, 3)
    with pytest.raises(ValueError):
        wilson_interval(-1, 10)
    with pytest.raises(ValueError):
        wilson_interval(1, 10, confidence=1.0)


def test_wilson_mas_confianza_da_intervalo_mas_ancho() -> None:
    estrecho = wilson_interval(30, 50, confidence=0.80)
    ancho = wilson_interval(30, 50, confidence=0.99)
    assert (ancho[1] - ancho[0]) > (estrecho[1] - estrecho[0])


def test_cada_frecuencia_trae_su_intervalo(europea) -> None:
    frecuencias = category_frequencies(europea, "color", ["1", "3", "5", "2", "0"])
    for f in frecuencias:
        assert f.observed_ci_low <= f.raw_count / f.raw_total <= f.observed_ci_high


def test_con_pocos_giros_el_intervalo_es_enorme(europea) -> None:
    """Que es exactamente el mensaje que debe llegar: con 5 giros no se sabe nada.

    Lo que NO se hace con esto es derivar un veredicto por grupo del tipo "esta
    desviacion se distingue del azar". Serian 13 pruebas simultaneas y en una
    rueda justa marcarian al menos un grupo en un tercio de las sesiones. El
    intervalo describe incertidumbre; afirmar es trabajo de `strength`, que esta
    corregida por comparaciones multiples.
    """
    for f in category_frequencies(europea, "color", ["1", "3", "5", "2", "0"]):
        assert f.observed_ci_high - f.observed_ci_low > 0.3
