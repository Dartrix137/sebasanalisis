"""Tests del motor de recomendacion (§2.10).

Sin base de datos ni red: el motor es Python puro y estos tests corren solos.

Las configuraciones de ruleta se leen del mismo `seed_data/` que carga el seed
(ver `conftest.py`), asi que si alguien cambia el JSON sembrado sin querer, esto
falla.
"""

import pytest

from app.engine.probability import GameConfig
from app.engine.recommendation import (
    CHI_SQUARE_BONUS,
    STRONG_THRESHOLD,
    WEIGHT_CONSISTENCY,
    WEIGHT_DEVIATION,
    WEIGHT_RECENCY,
    MIN_SPINS_FOR_SIGNAL,
    Decision,
    NoBetReason,
    Outcome,
    SignalBand,
    available_windows,
    band_for,
    market_catalog,
    market_for_key,
    no_bet_reason,
    recommend,
    resolve,
    score_market,
)

# --------------------------------------------------------------------------
# Catalogo de mercados
# --------------------------------------------------------------------------


def test_el_catalogo_cubre_los_mercados_del_comparativo(europea) -> None:
    """Rojo/negro, par/impar, bajo/alto, docenas, columnas, dos docenas y dos
    columnas — los siete grupos de mercados de §4 del comparativo."""
    claves = {m.key for m in market_catalog(europea)}
    assert {"color:red", "color:black"} <= claves
    assert {"parity:even", "parity:odd"} <= claves
    assert {"high_low:low", "high_low:high"} <= claves
    assert {"dozen:first", "dozen:second", "dozen:third"} <= claves
    assert {"column:first", "column:second", "column:third"} <= claves
    assert {"dozen:first+second", "dozen:first+third", "dozen:second+third"} <= claves
    assert {
        "column:first+second",
        "column:first+third",
        "column:second+third",
    } <= claves
    assert len(claves) == 18


def test_el_verde_no_es_un_mercado(europea, americana) -> None:
    """El 0 y el 00 nunca se recomiendan: el grupo verde lleva `market: false`.

    Sigue existiendo como grupo —lo necesitan las frecuencias de color y el
    chi-cuadrado—, pero no entra al catalogo."""
    for config in (europea, americana):
        assert "color:green" not in {m.key for m in market_catalog(config)}
        assert config.category("color").group("green") is not None


def test_las_combinaciones_cubren_dos_sectores_y_su_pago(europea) -> None:
    dos_docenas = market_for_key(europea, "dozen:first+second")
    assert dos_docenas is not None
    assert dos_docenas.sectors == 2
    assert dos_docenas.coverage == 24
    # El pago es el de cada docena; que el otro sector se pierda lo sabe
    # `bankroll`, no el catalogo.
    assert dos_docenas.payout == 2


def test_el_orden_del_catalogo_no_depende_del_orden_de_las_claves(europea) -> None:
    """JSONB no conserva el orden de las claves de un objeto, asi que el
    catalogo no puede salir de iterar `groups`. Se comprueba barajando las
    claves del diccionario y exigiendo el mismo orden."""
    crudo = {
        "possible_outcomes": list(europea.possible_outcomes),
        "categories": [
            {
                "id": c.id,
                "label": c.label,
                "shrinkage_alpha": c.shrinkage_alpha,
                "groups": {
                    g.id: {
                        "label": g.label,
                        "outcomes": sorted(g.outcomes),
                        "payout": g.payout,
                        "market": g.market,
                    }
                    # Orden invertido a proposito.
                    for g in reversed(c.groups)
                },
            }
            for c in europea.categories
        ],
        "allowed_combinations": [
            {
                "id": a.id,
                "label": a.label,
                "category_id": a.category_id,
                "group_ids": list(a.group_ids),
            }
            for a in europea.allowed_combinations
        ],
    }
    barajada = GameConfig.from_dict(crudo)
    assert [m.key for m in market_catalog(barajada)] == [
        m.key for m in market_catalog(europea)
    ]


# --------------------------------------------------------------------------
# Probabilidades por variante
# --------------------------------------------------------------------------


def test_europea_y_americana_dan_teoricas_y_cobertura_distintas(
    europea, americana
) -> None:
    """El mismo mercado no vale lo mismo en las dos variantes (§2.1)."""
    casos = [
        ("color:red", 18, 18 / 37, 18 / 38),
        ("dozen:first", 12, 12 / 37, 12 / 38),
        ("dozen:first+second", 24, 24 / 37, 24 / 38),
        ("column:first+second", 24, 24 / 37, 24 / 38),
    ]
    for clave, cobertura, p_eu, p_am in casos:
        m_eu = market_for_key(europea, clave)
        m_am = market_for_key(americana, clave)
        assert m_eu.coverage == m_am.coverage == cobertura

        w_eu = score_market(europea, m_eu, ["1"] * 10).windows[-1]
        w_am = score_market(americana, m_am, ["1"] * 10).windows[-1]
        assert w_eu.theoretical_probability == pytest.approx(p_eu, abs=1e-9)
        assert w_am.theoretical_probability == pytest.approx(p_am, abs=1e-9)
        assert w_eu.theoretical_probability > w_am.theoretical_probability


def test_el_cero_y_el_doble_cero_no_suman_a_ningun_mercado(europea, americana) -> None:
    """Un historial de puros ceros no puede dejar ningun mercado por encima de
    su teorica: el 0 y el 00 no pertenecen a color, paridad, alto/bajo, docena
    ni columna."""
    for config, ceros in ((europea, ["0"] * 60), (americana, ["0", "00"] * 30)):
        for m in market_catalog(config):
            resultado = score_market(config, m, ceros)
            assert resultado.windows[-1].raw_count == 0
            assert resultado.windows[-1].deviation < 0
            assert resultado.signal_score == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Score y bandas
# --------------------------------------------------------------------------


def test_historial_uniforme_no_recomienda(europea) -> None:
    """Una mesa que reparte todo por igual no da señal: SIN SEÑAL, NO APOSTAR.

    "Por igual" en todas las ventanas que mira el motor, no solo en el total:
    cada numero una vez por vuelta, en un orden (paso 16 modulo 37) que no
    agrupa ningun mercado en los giros recientes.
    """
    numeros = list(europea.possible_outcomes)
    vuelta = [numeros[(i * 16) % len(numeros)] for i in range(len(numeros))]
    uniforme = vuelta * 6  # 222 giros, cada numero seis veces
    # Precondicion: ningun mercado se separa de su teorica en ninguna ventana.
    for m in market_catalog(europea):
        for w in score_market(europea, m, uniforme).windows:
            assert abs(w.z) < 0.5

    resultado = recommend(europea, uniforme)
    assert resultado.decision is Decision.no_bet
    assert resultado.signal_band is SignalBand.weak
    assert resultado.signal_score < resultado.threshold
    # El mejor candidato viaja igual, para que el backtest pueda analizarlo.
    assert resultado.best is not None
    assert resultado.market is None


def test_una_racha_reciente_da_señal_aunque_el_total_este_parejo(europea) -> None:
    """Cada numero sale seis veces, pero en orden: los ultimos diez giros son
    27-36, todos altos. Desde la calibracion del 2026-09-24 la consistencia
    pesa 0.10 y ya no frena una desviacion reciente grande aunque los tramos
    viejos se cancelen: el motor lo marca.

    Es una decision de calibracion, no un descubrimiento: en una mesa justa esa
    racha no cambia la probabilidad del giro siguiente, que sigue siendo la
    teorica.
    """
    barrido = list(europea.possible_outcomes) * 6
    resultado = recommend(europea, barrido)
    assert resultado.decision is Decision.recommend
    assert resultado.market is not None
    assert resultado.market.key == "high_low:high"
    assert resultado.best is not None
    assert resultado.best.components.consistency is not None
    assert resultado.best.components.consistency < 0.5


def test_las_bandas_cortan_en_los_dos_umbrales() -> None:
    """Tres estados: SIN SEÑAL bajo el minimo, MEDIA del minimo al alto,
    FUERTE desde el alto. Los dos pisos son inclusivos."""
    assert STRONG_THRESHOLD == 80
    assert band_for(0, 60) is SignalBand.weak
    assert band_for(59.99, 60) is SignalBand.weak
    assert band_for(60, 60) is SignalBand.medium
    assert band_for(68, 60) is SignalBand.medium
    assert band_for(79.99, 60) is SignalBand.medium
    assert band_for(80, 60) is SignalBand.strong
    assert band_for(100, 60) is SignalBand.strong


def test_el_umbral_minimo_mueve_el_piso_de_la_media() -> None:
    assert band_for(55, 50) is SignalBand.medium
    assert band_for(65, 70) is SignalBand.weak


def test_con_el_minimo_por_encima_del_alto_no_hay_media() -> None:
    """Si el admin sube el umbral minimo por encima de 80, todo lo que se
    recomienda es FUERTE, y lo que queda debajo del minimo es SIN SEÑAL aunque
    pase de 80: la banda nunca contradice a la decision."""
    assert band_for(84.99, 85) is SignalBand.weak
    assert band_for(85, 85) is SignalBand.strong


def test_la_banda_nunca_contradice_a_la_decision(europea) -> None:
    """Una recomendacion es MEDIA o FUERTE; un NO_BET es siempre SIN SEÑAL,
    tambien en el mejor candidato y en los demas mercados."""
    giros = ["1"] * 30 + list(europea.possible_outcomes)
    puntaje = recommend(europea, giros).signal_score
    for umbral in (puntaje - 1, puntaje, puntaje + 1):
        resultado = recommend(europea, giros, threshold=umbral)
        if resultado.decision is Decision.recommend:
            assert resultado.signal_band in (SignalBand.medium, SignalBand.strong)
        else:
            assert resultado.signal_band is SignalBand.weak
        for c in resultado.candidates:
            assert (c.signal_band is SignalBand.weak) == (c.signal_score < umbral)


def test_justo_en_el_umbral_recomienda_y_un_punto_por_debajo_no(europea) -> None:
    """El umbral es inclusivo: alcanzarlo exacto basta para recomendar."""
    giros = ["1"] * 30 + list(europea.possible_outcomes)
    puntaje = recommend(europea, giros).signal_score

    justo = recommend(europea, giros, threshold=puntaje)
    assert justo.decision is Decision.recommend

    por_encima = recommend(europea, giros, threshold=puntaje + 1)
    assert por_encima.decision is Decision.no_bet
    # Cambiar el umbral no cambia el puntaje: solo la decision.
    assert por_encima.signal_score == pytest.approx(puntaje)


def test_el_score_esta_acotado_entre_0_y_100(europea) -> None:
    extremos = [
        [],
        ["1"],
        ["1"] * 400,
        list(europea.possible_outcomes) * 3,
    ]
    for giros in extremos:
        for candidato in recommend(europea, giros).candidates:
            assert 0.0 <= candidato.signal_score <= 100.0


def test_solo_cuenta_la_desviacion_por_encima_de_la_teorica(europea) -> None:
    """Un mercado que salio MENOS de lo esperado no suma puntos.

    Recomendar lo que no ha salido seria la falacia del jugador."""
    # 60 rojos seguidos: negro quedo muy por debajo de su teorica.
    rojos = ["1", "3", "5", "7", "9", "12"] * 10
    negro = score_market(europea, market_for_key(europea, "color:black"), rojos)
    rojo = score_market(europea, market_for_key(europea, "color:red"), rojos)

    assert negro.windows[-1].deviation < 0
    assert negro.signal_score == pytest.approx(0.0)
    assert rojo.windows[-1].deviation > 0
    assert rojo.signal_score > negro.signal_score


def test_la_consistencia_queda_indefinida_con_un_solo_tramo(europea) -> None:
    """Con menos de 10 giros hay un unico tramo, y un tramo no tiene con que ser
    consistente. Su peso se reparte entre desviacion y recencia en vez de
    regalar sus puntos a cualquier mercado que asome por encima de la teorica."""
    cinco_rojos = ["1", "3", "5", "7", "9"]
    resultado = score_market(europea, market_for_key(europea, "color:red"), cinco_rojos)

    assert resultado.components.consistency is None
    assert resultado.components.weight_consistency == 0.0
    esperado = 100 * (
        WEIGHT_DEVIATION * resultado.components.deviation
        + WEIGHT_RECENCY * resultado.components.recency
    ) / (WEIGHT_DEVIATION + WEIGHT_RECENCY)
    assert resultado.signal_score == pytest.approx(esperado)


def test_sin_los_giros_minimos_no_recomienda_aunque_llegue_al_umbral(europea) -> None:
    """Cinco rojos seguidos pasan el umbral de 50, pero cinco giros no
    sostienen nada: SIN SEÑAL por falta de informacion, tambien en la banda."""
    cinco_rojos = ["1", "3", "5", "7", "9"]
    resultado = recommend(europea, cinco_rojos)

    assert resultado.best is not None
    assert resultado.best.signal_score >= europea.recommendation_threshold
    assert resultado.decision is Decision.no_bet
    assert resultado.market is None
    assert no_bet_reason(resultado.decision, len(cinco_rojos)) is NoBetReason.insufficient_data
    assert all(c.signal_band is SignalBand.weak for c in resultado.candidates)


def test_con_los_giros_minimos_ya_puede_recomendar(europea) -> None:
    diez_rojos = ["1", "3", "5", "7", "9", "12", "14", "16", "18", "19"]
    assert len(diez_rojos) == MIN_SPINS_FOR_SIGNAL
    resultado = recommend(europea, diez_rojos)
    assert resultado.decision is Decision.recommend


def test_con_varios_tramos_la_consistencia_entra_al_score(europea) -> None:
    giros = ["1"] * 25
    resultado = score_market(europea, market_for_key(europea, "color:red"), giros)
    assert resultado.components.consistency is not None
    assert resultado.components.weight_consistency == WEIGHT_CONSISTENCY


def test_los_pesos_suman_uno() -> None:
    assert WEIGHT_DEVIATION + WEIGHT_RECENCY + WEIGHT_CONSISTENCY == pytest.approx(1.0)


def test_las_ventanas_son_las_del_documento() -> None:
    assert available_windows(0) == ()
    # Con menos giros que la ventana mas corta, el historial entero es la ventana.
    assert available_windows(4) == (4,)
    assert available_windows(10) == (10,)
    assert available_windows(35) == (10, 20)
    assert available_windows(120) == (10, 20, 50, 100)
    assert available_windows(500) == (10, 20, 50, 100)


# --------------------------------------------------------------------------
# Chi-cuadrado
# --------------------------------------------------------------------------


def test_el_chi_cuadrado_no_suma_con_menos_de_200_giros(europea) -> None:
    giros = ["1"] * 150
    for candidato in recommend(europea, giros).candidates:
        assert candidato.components.chi_square_bonus == 0.0
        assert candidato.chi_square_pvalue_adjusted is None


def test_el_chi_cuadrado_suma_su_bono_cuando_esta_activo(europea) -> None:
    """Con 240 giros cargados a una docena la prueba se activa y suma sus
    puntos. El p-valor que viaja es el corregido por Benjamini-Hochberg."""
    sesgados = ["1", "2", "3", "4"] * 60  # 240 giros, todos en la 1a docena
    resultado = recommend(europea, sesgados)
    primera = next(
        c for c in resultado.candidates if c.market.key == "dozen:first"
    )
    assert primera.components.chi_square_bonus == CHI_SQUARE_BONUS
    assert primera.chi_square_pvalue_adjusted is not None
    assert primera.chi_square_pvalue_adjusted < 0.05


def test_el_chi_cuadrado_mira_el_historial_completo_no_la_ventana(europea) -> None:
    """Misma separacion que en `ranking`: la ventana de recencia es un limite de
    rendimiento y al chi-cuadrado no se le aplica (§2.4)."""
    completo = ["1", "2", "3", "4"] * 60
    ventana = completo[-50:]

    con_historial = recommend(europea, ventana, full_history=completo)
    sin_historial = recommend(europea, ventana)

    def bono(r):
        return next(
            c.components.chi_square_bonus
            for c in r.candidates
            if c.market.key == "dozen:first"
        )

    assert bono(con_historial) == CHI_SQUARE_BONUS
    assert bono(sin_historial) == 0.0


# --------------------------------------------------------------------------
# Una sola recomendacion, y determinista
# --------------------------------------------------------------------------


def test_devuelve_una_sola_recomendacion(europea) -> None:
    resultado = recommend(europea, ["1"] * 40)
    assert resultado.market is None or isinstance(resultado.market.key, str)
    assert resultado.best is resultado.candidates[0]


def test_el_desempate_es_determinista(europea) -> None:
    """Dos corridas sobre los mismos datos dan exactamente el mismo mercado y el
    mismo orden completo de candidatos."""
    giros = ["1", "5", "9", "0", "13", "22", "7"] * 12
    a = recommend(europea, giros)
    b = recommend(europea, giros)
    assert [c.market.key for c in a.candidates] == [c.market.key for c in b.candidates]
    assert a.best.market.key == b.best.market.key


def test_a_igual_score_gana_la_menor_cobertura(europea) -> None:
    """Regla de desempate de §2.10: mayor score, luego MENOR cobertura, luego
    orden de catalogo. Se comprueba sobre los candidatos empatados en 0."""
    uniforme = list(europea.possible_outcomes) * 6
    empatados = [
        c for c in recommend(europea, uniforme).candidates
        if c.signal_score == pytest.approx(0.0)
    ]
    coberturas = [c.market.coverage for c in empatados]
    assert coberturas == sorted(coberturas)


def test_funciona_con_un_juego_que_no_es_ruleta(dados) -> None:
    """El motor no tiene ruleta hardcodeada: un juego sin combinaciones ni
    docenas se evalua igual."""
    resultado = recommend(dados, ["2", "4", "6", "8", "10", "12"] * 8)
    assert {c.market.key for c in resultado.candidates} == {
        "parity:even",
        "parity:odd",
    }
    assert resultado.best.market.key == "parity:even"


# --------------------------------------------------------------------------
# Explicacion
# --------------------------------------------------------------------------


def test_cada_candidato_trae_teorica_y_observada_juntas(europea) -> None:
    """Regla anti-falacia del jugador (§2): la frecuencia observada nunca viaja
    sola. En Fase 3 la pareja vive en la respuesta de la API y en la seccion
    desplegable, no en la tarjeta principal."""
    for candidato in recommend(europea, ["1"] * 40).candidates:
        for ventana in candidato.windows:
            assert 0 < ventana.theoretical_probability < 1
            assert 0 <= ventana.observed_frequency_shrunk <= 1
            assert ventana.deviation == pytest.approx(
                ventana.observed_frequency_shrunk - ventana.theoretical_probability
            )
            assert ventana.observed_ci_low <= ventana.observed_ci_high


def test_hay_una_ventana_por_cada_ventana_disponible(europea) -> None:
    giros = ["1"] * 120
    candidato = recommend(europea, giros).candidates[0]
    assert tuple(w.spins_used for w in candidato.windows) == available_windows(120)


def test_sin_giros_no_hay_score_ni_ventanas(europea) -> None:
    resultado = recommend(europea, [])
    assert resultado.decision is Decision.no_bet
    assert all(c.signal_score == 0.0 for c in resultado.candidates)
    assert all(c.windows == () for c in resultado.candidates)


def test_el_minimo_de_giros_es_la_ventana_mas_corta() -> None:
    assert MIN_SPINS_FOR_SIGNAL == 10


def test_sin_giros_suficientes_el_no_apostar_es_por_falta_de_informacion() -> None:
    assert no_bet_reason(Decision.no_bet, 0) is NoBetReason.insufficient_data
    assert no_bet_reason(Decision.no_bet, 9) is NoBetReason.insufficient_data


def test_con_giros_suficientes_el_no_apostar_es_por_el_umbral() -> None:
    assert no_bet_reason(Decision.no_bet, 10) is NoBetReason.below_threshold
    assert no_bet_reason(Decision.no_bet, 500) is NoBetReason.below_threshold


def test_una_recomendacion_no_trae_motivo_de_no_apostar() -> None:
    """El minimo explica el silencio; no bloquea una recomendacion."""
    assert no_bet_reason(Decision.recommend, 3) is None
    assert no_bet_reason(Decision.recommend, 100) is None


# --------------------------------------------------------------------------
# Resolucion
# --------------------------------------------------------------------------


def test_una_recomendacion_se_resuelve_con_el_giro_siguiente(europea) -> None:
    rojo = market_for_key(europea, "color:red")
    assert resolve(rojo, "1") is Outcome.hit      # el 1 es rojo
    assert resolve(rojo, "2") is Outcome.miss     # el 2 es negro
    assert resolve(rojo, "0") is Outcome.miss     # el 0 no es de nadie


def test_dos_docenas_acierta_si_el_numero_cae_en_cualquiera(europea) -> None:
    dos = market_for_key(europea, "dozen:first+second")
    assert resolve(dos, "5") is Outcome.hit
    assert resolve(dos, "20") is Outcome.hit
    assert resolve(dos, "30") is Outcome.miss
    assert resolve(dos, "0") is Outcome.miss


def test_no_apostar_no_se_resuelve(europea) -> None:
    """Un NO APOSTAR no acerto ni fallo: no hubo nada que acertar."""
    assert resolve(None, "1") is Outcome.pending
    assert resolve(None, "0") is Outcome.pending
