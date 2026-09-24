"""Progresiones de banca (§2.8).

Las dos tablas de regresion vienen del documento de estrategia verificado, via
la skill `motor-estadistico-testing`. No se recalculan de memoria.
"""

import pytest

from app.engine.bankroll import (
    BANKROLL_DISCLAIMER,
    OFFERED_STRATEGIES,
    AlertLevel,
    advance_stages_on_outcome,
    applies_to_market,
    cumulative_risked_on_market,
    net_if_won_on_market,
    stake_for_market,
    stakes_for_market,
    Strategy,
    StrategyMode,
    StopReason,
    advance_stage,
    advance_stage_by_round,
    bankroll_alerts,
    bankroll_plan,
    bet_for_stage,
    cumulative_risked,
    eligible_bets,
    max_affordable_stages,
    mode_for,
    net_result_if_won,
    progression_table,
    recovers_only_to_break_even,
    ruin_probability_estimate,
    stage_multiplier,
    stages_supported_from,
    stop_reason,
    suggest_bet,
    validate_combination,
)
from app.engine.probability import GameConfig, combined_probability

# ---------- Tabla de regresion: martingala 1:1, base $100 ----------

MARTINGALA_100 = [
    (1, 100, 100),
    (2, 200, 300),
    (3, 400, 700),
    (4, 800, 1_500),
    (5, 1_600, 3_100),
    (6, 3_200, 6_300),
    (7, 6_400, 12_700),
    (8, 12_800, 25_500),
    (9, 25_600, 51_100),
    (10, 51_200, 102_300),
]


@pytest.mark.parametrize(("escalon", "apuesta", "acumulado"), MARTINGALA_100)
def test_tabla_de_martingala_del_documento_verificado(
    escalon: int, apuesta: float, acumulado: float
) -> None:
    stage = escalon - 1
    assert bet_for_stage(Strategy.martingale, 100, stage) == apuesta
    assert cumulative_risked(Strategy.martingale, 100, stage) == acumulado


def test_diez_perdidas_de_martingala_cuestan_102300_no_100000() -> None:
    """El error del documento original era decir $100.000; el correcto es $102.300."""
    acumulado = cumulative_risked(Strategy.martingale, 100, 9)
    assert acumulado == 102_300
    assert acumulado != 100_000


# ---------- Tabla de regresion: dos sectores, unidad $100 ----------

DOS_SECTORES_100 = [
    (1, 100, 200, 200),
    (2, 200, 400, 600),
    (3, 600, 1_200, 1_800),
    (4, 1_800, 3_600, 5_400),
    (5, 5_400, 10_800, 16_200),
]


@pytest.mark.parametrize(
    ("escalon", "por_sector", "total_giro", "acumulado"), DOS_SECTORES_100
)
def test_tabla_de_dos_sectores_del_documento_verificado(
    escalon: int, por_sector: float, total_giro: float, acumulado: float
) -> None:
    stage = escalon - 1
    fila = progression_table(Strategy.two_sector_recovery, 100, stages=5)[stage]
    assert fila.bet_per_sector == por_sector
    assert fila.total_bet == total_giro
    assert fila.cumulative_loss == acumulado


def test_cinco_perdidas_en_dos_sectores_cuestan_16200() -> None:
    assert cumulative_risked(Strategy.two_sector_recovery, 100, 4) == 16_200


def test_el_sexto_escalon_de_dos_sectores_exige_16200_por_docena() -> None:
    """El documento verificado lo dice explicitamente: $16.200 por docena, $32.400 en total."""
    assert bet_for_stage(Strategy.two_sector_recovery, 100, 5) == 32_400
    fila = progression_table(Strategy.two_sector_recovery, 100, stages=6)[5]
    assert fila.bet_per_sector == 16_200


def test_dos_sectores_cubre_dos_grupos_por_giro() -> None:
    consejo = suggest_bet(
        Strategy.two_sector_recovery, 100, 0, bankroll_current=100_000
    )
    assert consejo.sectors == 2
    assert consejo.suggested_bet == consejo.bet_per_sector * 2


# ---------- Progresiones de modo 1:1 ----------


def test_flat_no_cambia_nunca_la_apuesta() -> None:
    assert [stage_multiplier(Strategy.flat, s) for s in range(5)] == [1.0] * 5


# ---------- Avance de escalon ----------


@pytest.mark.parametrize(
    ("strategy", "stage", "won", "esperado"),
    [
        (Strategy.flat, 0, False, 0),
        (Strategy.flat, 0, True, 0),
        (Strategy.martingale, 3, False, 4),
        (Strategy.martingale, 3, True, 0),
        (Strategy.two_sector_recovery, 2, False, 3),
        (Strategy.two_sector_recovery, 2, True, 0),
    ],
)
def test_avance_de_escalon(
    strategy: Strategy, stage: int, won: bool, esperado: int
) -> None:
    assert advance_stage(strategy, stage, won) == esperado


# ---------- Validacion cruzada modo/estrategia (§2.8) ----------


@pytest.mark.parametrize(
    "strategy",
    [Strategy.flat, Strategy.martingale],
)
def test_las_estrategias_1a1_son_de_modo_single(strategy: Strategy) -> None:
    assert mode_for(strategy) is StrategyMode.single
    validate_combination(strategy, StrategyMode.single)


def test_la_recuperacion_de_dos_sectores_es_de_su_propio_modo() -> None:
    assert mode_for(Strategy.two_sector_recovery) is StrategyMode.two_sector
    validate_combination(Strategy.two_sector_recovery, StrategyMode.two_sector)


@pytest.mark.parametrize(
    ("strategy", "mode"),
    [
        (Strategy.martingale, StrategyMode.two_sector),
        (Strategy.two_sector_recovery, StrategyMode.single),
    ],
)
def test_mezclar_modo_y_estrategia_se_rechaza(
    strategy: Strategy, mode: StrategyMode
) -> None:
    """El motor nunca interpreta una combinacion invalida: la rechaza."""
    with pytest.raises(ValueError):
        validate_combination(strategy, mode)


# ---------- Limites de mesa y de banca ----------


def test_la_tabla_marca_donde_se_rompe_la_progresion() -> None:
    filas = progression_table(
        Strategy.martingale, 100, stages=10, table_limit=5_000, bankroll=10_000
    )
    # $6.400 (escalon 7) es la primera apuesta que la mesa no aceptaria.
    assert [f.stage for f in filas if f.exceeds_table_limit][0] == 6
    # $12.700 acumulado (escalon 7) es lo primero que la banca no cubre.
    assert [f.stage for f in filas if f.exceeds_bankroll][0] == 6


def test_escalones_que_la_banca_soporta() -> None:
    # Con $10.000 se cubren los escalones hasta $6.300 acumulados; el septimo
    # llevaria a $12.700 y no alcanza.
    assert max_affordable_stages(Strategy.martingale, 100, 10_000) == 6


def test_el_limite_de_mesa_recorta_los_escalones() -> None:
    assert (
        max_affordable_stages(
            Strategy.martingale, 100, 1_000_000, table_limit=1_000
        )
        == 4
    )


def test_banca_que_no_cubre_ni_el_primer_escalon() -> None:
    assert max_affordable_stages(Strategy.martingale, 100, 50) == 0
    assert ruin_probability_estimate(Strategy.martingale, 100, 50, 18 / 37) == 1.0


# ---------- Riesgo de agotar la banca ----------


def test_el_riesgo_es_la_cola_de_derrotas_consecutivas() -> None:
    """Giros independientes: 6 derrotas seguidas a p=18/37 de ganar."""
    p = 18 / 37
    esperado = (1 - p) ** 6
    assert ruin_probability_estimate(
        Strategy.martingale, 100, 10_000, p
    ) == pytest.approx(esperado)


def test_mas_banca_reduce_el_riesgo_pero_nunca_lo_anula() -> None:
    p = 18 / 37
    poca = ruin_probability_estimate(Strategy.martingale, 100, 10_000, p)
    mucha = ruin_probability_estimate(Strategy.martingale, 100, 10_000_000, p)
    assert 0 < mucha < poca


def test_la_progresion_no_mejora_la_probabilidad_del_giro() -> None:
    """Todas las progresiones parten del mismo p; solo cambia cuanto aguantan."""
    p = 18 / 37
    riesgos = {
        s: ruin_probability_estimate(s, 100, 10_000, p)
        for s in (Strategy.flat, Strategy.martingale)
    }
    # La martingala se agota mucho antes que la plana con la misma banca.
    assert riesgos[Strategy.martingale] > riesgos[Strategy.flat]


# ---------- Advertencias de riesgo ----------


def test_la_advertencia_aparece_al_avanzar_en_una_progresion_exponencial() -> None:
    consejo = suggest_bet(
        Strategy.martingale, 100, 4, bankroll_current=100_000
    )
    assert consejo.risk_warning is not None
    assert "exponencial" in consejo.risk_warning
    assert BANKROLL_DISCLAIMER in consejo.risk_warning


def test_avisa_cuando_el_escalon_supera_la_banca() -> None:
    consejo = suggest_bet(Strategy.martingale, 100, 9, bankroll_current=1_000)
    assert consejo.exceeds_bankroll
    assert consejo.risk_warning is not None
    assert "banca" in consejo.risk_warning


def test_avisa_cuando_el_escalon_supera_el_limite_de_mesa() -> None:
    consejo = suggest_bet(
        Strategy.martingale, 100, 9, bankroll_current=1_000_000, table_limit=5_000
    )
    assert consejo.exceeds_table_limit
    assert consejo.risk_warning is not None
    assert "mesa" in consejo.risk_warning


def test_el_primer_escalon_plano_no_necesita_advertencia() -> None:
    consejo = suggest_bet(Strategy.flat, 100, 0, bankroll_current=100_000)
    assert consejo.risk_warning is None
    assert consejo.suggested_bet == 100


def test_la_advertencia_nunca_usa_lenguaje_predictivo() -> None:
    prohibidas = ("predic", "va a salir", "seguro", "garantiz", "proximo numero")
    consejo = suggest_bet(
        Strategy.two_sector_recovery,
        100,
        4,
        bankroll_current=20_000,
        probability_of_winning_the_bet=24 / 37,
    )
    assert consejo.risk_warning is not None
    texto = consejo.risk_warning.lower()
    for palabra in prohibidas:
        assert palabra not in texto
    assert BANKROLL_DISCLAIMER in consejo.risk_warning


def test_el_disclaimer_dice_que_no_cambia_la_ventaja_de_la_casa() -> None:
    texto = BANKROLL_DISCLAIMER.lower()
    assert "ninguna progresion" in texto
    assert "cambia la probabilidad" in texto
    assert "ventaja de la casa" in texto


# ---------- Entradas invalidas ----------


def test_rechaza_apuesta_base_no_positiva() -> None:
    with pytest.raises(ValueError):
        bet_for_stage(Strategy.martingale, 0, 0)


def test_rechaza_escalon_negativo() -> None:
    with pytest.raises(ValueError):
        stage_multiplier(Strategy.martingale, -1)


def test_rechaza_probabilidad_fuera_de_rango() -> None:
    with pytest.raises(ValueError):
        ruin_probability_estimate(Strategy.martingale, 100, 10_000, 1.5)


# ---------- Pureza ----------


def test_es_una_funcion_pura() -> None:
    """Mismo input, mismo output, sin estado compartido."""
    a = suggest_bet(Strategy.martingale, 100, 3, bankroll_current=10_000)
    b = suggest_bet(Strategy.martingale, 100, 3, bankroll_current=10_000)
    assert a == b


# ---------- Con cuanto queda la serie si se gana ----------


def test_ganar_con_martingala_deja_siempre_una_apuesta_base() -> None:
    for stage in range(6):
        assert net_result_if_won(Strategy.martingale, 100, stage) == 100


def test_ganar_en_dos_sectores_solo_recupera_no_deja_ganancia() -> None:
    """Del escalon 2 en adelante la serie vuelve a cero, no a ganancia.

    La apuesta por sector de un escalon es justo la perdida acumulada del
    anterior, asi que acertar recupera lo perdido y nada mas. Es la diferencia
    de fondo con la martingala 1:1 y debe quedar visible en la UI.
    """
    assert net_result_if_won(Strategy.two_sector_recovery, 100, 0) == 100
    for stage in range(1, 6):
        assert net_result_if_won(Strategy.two_sector_recovery, 100, stage) == 0
        assert recovers_only_to_break_even(Strategy.two_sector_recovery, 100, stage)


def test_el_primer_escalon_de_dos_sectores_si_deja_ganancia() -> None:
    assert not recovers_only_to_break_even(Strategy.two_sector_recovery, 100, 0)


# ---------- Apuestas elegibles segun el modo ----------

RULETA_EUROPEA = {
    "possible_outcomes": [str(n) for n in range(37)],
    "categories": [
        {
            "id": "color",
            "label": "Color",
            "shrinkage_alpha": 8,
            "groups": {
                "red": {
                    "label": "Rojo",
                    "outcomes": ["1", "3", "5", "7", "9", "12", "14", "16", "18",
                                 "19", "21", "23", "25", "27", "30", "32", "34", "36"],
                    "payout": 1,
                },
                "black": {
                    "label": "Negro",
                    "outcomes": ["2", "4", "6", "8", "10", "11", "13", "15", "17",
                                 "20", "22", "24", "26", "28", "29", "31", "33", "35"],
                    "payout": 1,
                },
            },
        },
        {
            "id": "docena",
            "label": "Docena",
            "shrinkage_alpha": 8,
            "groups": {
                "d1": {"label": "1a docena", "outcomes": [str(n) for n in range(1, 13)], "payout": 2},
                "d2": {"label": "2a docena", "outcomes": [str(n) for n in range(13, 25)], "payout": 2},
                "d3": {"label": "3a docena", "outcomes": [str(n) for n in range(25, 37)], "payout": 2},
            },
        },
    ],
}


@pytest.fixture
def europea() -> GameConfig:
    return GameConfig.from_dict(RULETA_EUROPEA)


def test_el_modo_1a1_ofrece_los_grupos_de_pago_par(europea: GameConfig) -> None:
    apuestas = eligible_bets(europea, StrategyMode.single)
    assert {a.id for a in apuestas} == {"color:red", "color:black"}
    for a in apuestas:
        assert a.theoretical_probability == pytest.approx(18 / 37, abs=0.0001)


def test_el_modo_dos_sectores_ofrece_las_tres_parejas_de_docenas(
    europea: GameConfig,
) -> None:
    """§2.8: no hay razon para preferir una pareja, asi que se ofrecen todas."""
    apuestas = eligible_bets(europea, StrategyMode.two_sector)
    assert len(apuestas) == 3
    assert {a.id for a in apuestas} == {
        "docena:d1+d2",
        "docena:d1+d3",
        "docena:d2+d3",
    }
    for a in apuestas:
        assert a.theoretical_probability == pytest.approx(24 / 37, abs=0.0001)


def test_las_apuestas_elegibles_traen_etiqueta_legible(europea: GameConfig) -> None:
    apuestas = eligible_bets(europea, StrategyMode.two_sector)
    etiquetas = {a.label for a in apuestas}
    assert "Docena: 1a docena + 2a docena" in etiquetas


# Un juego sin nada de ruleta: dado de 6 caras. Par/impar paga 1:1 y los
# tercios pagan 2:1, que es la unica estructura que el motor necesita conocer.
DADO_6 = {
    "possible_outcomes": ["1", "2", "3", "4", "5", "6"],
    "categories": [
        {
            "id": "paridad",
            "label": "Paridad",
            "shrinkage_alpha": 4,
            "groups": {
                "par": {"label": "Par", "outcomes": ["2", "4", "6"], "payout": 1},
                "impar": {"label": "Impar", "outcomes": ["1", "3", "5"], "payout": 1},
            },
        },
        {
            "id": "tercio",
            "label": "Tercio",
            "shrinkage_alpha": 4,
            "groups": {
                "t1": {"label": "Bajo", "outcomes": ["1", "2"], "payout": 2},
                "t2": {"label": "Medio", "outcomes": ["3", "4"], "payout": 2},
                "t3": {"label": "Alto", "outcomes": ["5", "6"], "payout": 2},
            },
        },
    ],
}


def test_el_motor_sirve_a_un_juego_que_no_es_ruleta() -> None:
    """Las apuestas se derivan del `payout`, nunca del nombre de la categoria.

    Es la propiedad que permite agregar dados sin tocar `engine/`: un juego con
    otras etiquetas y otro numero de resultados pasa por el mismo codigo.
    """
    dado = GameConfig.from_dict(DADO_6)

    unoauno = eligible_bets(dado, StrategyMode.single)
    assert {a.id for a in unoauno} == {"paridad:par", "paridad:impar"}
    for a in unoauno:
        assert a.theoretical_probability == pytest.approx(0.5)

    dos_sectores = eligible_bets(dado, StrategyMode.two_sector)
    assert len(dos_sectores) == 3  # las tres parejas de tercios
    for a in dos_sectores:
        assert a.theoretical_probability == pytest.approx(4 / 6)

    # Y la progresion de recuperacion funciona igual con esta configuracion.
    assert cumulative_risked(Strategy.two_sector_recovery, 50, 4) == 8_100


def test_probabilidad_combinada_rechaza_grupos_que_se_solapan(
    europea: GameConfig,
) -> None:
    """Sumar grupos solapados contaria resultados dos veces."""
    with pytest.raises(ValueError):
        combined_probability(europea, [("color", "red"), ("color", "red")])


def test_probabilidad_combinada_de_dos_docenas(europea: GameConfig) -> None:
    p = combined_probability(europea, [("docena", "d1"), ("docena", "d2")])
    assert p == pytest.approx(24 / 37, abs=0.0001)


# ---------- Avance de escalon con varias apuestas en el mismo giro ----------


@pytest.mark.parametrize(
    ("strategy", "stage", "neto", "esperado"),
    [
        # Giro en positivo: cuenta como victoria.
        (Strategy.martingale, 3, 500, 0),
        # Giro en negativo: cuenta como derrota.
        (Strategy.martingale, 3, -500, 4),
        # Giro que cierra en cero: el escalon no se mueve.
        (Strategy.martingale, 3, 0, 3),
        # La plana no tiene escalon que mover.
        (Strategy.flat, 0, -500, 0),
        (Strategy.flat, 0, 0, 0),
    ],
)
def test_avance_por_el_neto_del_giro(
    strategy: Strategy, stage: int, neto: float, esperado: int
) -> None:
    assert advance_stage_by_round(strategy, stage, neto) == esperado


def test_ganar_una_y_perder_otra_se_decide_por_el_neto() -> None:
    """Dos apuestas: +2.000 y -1.000. El giro cerro adelante, asi que es victoria."""
    assert advance_stage_by_round(Strategy.martingale, 2, 2_000 - 1_000) == 0


def test_ganar_una_pequena_y_perder_una_grande_es_derrota() -> None:
    assert advance_stage_by_round(Strategy.martingale, 2, 1_000 - 3_000) == 3


def test_coincide_con_el_avance_simple_cuando_hay_una_sola_apuesta() -> None:
    """Una apuesta suelta tiene que comportarse igual que antes."""
    for strategy in (Strategy.martingale, Strategy.two_sector_recovery):
        for stage in range(4):
            assert advance_stage_by_round(strategy, stage, 100) == advance_stage(
                strategy, stage, True
            )
            assert advance_stage_by_round(strategy, stage, -100) == advance_stage(
                strategy, stage, False
            )


# ---------- Siguiente paso de la progresion ----------


def test_siguiente_paso_de_martingala_con_la_tabla_del_documento() -> None:
    """Escalon 3 de la tabla ($400) tras perder $100 y $200 de una banca de $10.000."""
    plan = bankroll_plan(
        Strategy.martingale, 100, 2, bankroll_current=9_700, bankroll_start=10_000
    )
    assert plan.if_lost.stage == 3
    assert plan.if_lost.suggested_bet == 800
    assert plan.if_lost.bankroll_after == 9_300
    assert plan.if_won.stage == 0
    assert plan.if_won.suggested_bet == 100
    # Ganar el escalon 3 deja la serie en +$100: la banca termina en $10.100.
    assert plan.if_won.bankroll_after == 10_100


def test_siguiente_paso_de_dos_sectores_con_la_tabla_del_documento() -> None:
    """Escalon 2 ($200 por docena): perder lleva a $600 por docena, $1.200 el giro."""
    plan = bankroll_plan(
        Strategy.two_sector_recovery,
        100,
        1,
        bankroll_current=9_800,
        bankroll_start=10_000,
    )
    assert plan.if_lost.stage == 2
    assert plan.if_lost.bet_per_sector == 600
    assert plan.if_lost.suggested_bet == 1_200
    assert plan.if_lost.bankroll_after == 9_400
    # Una docena acierta (+$400) y la otra se pierde (-$200): la banca sube $200 y
    # vuelve a $10.000, que es justo lo que dice "recupera, no deja ganancia".
    assert plan.if_won.stage == 0
    assert plan.if_won.bankroll_after == 10_000


@pytest.mark.parametrize(
    ("strategy", "stage", "si_gana", "si_pierde"),
    [
        (Strategy.flat, 0, 0, 0),
    ],
)
def test_el_siguiente_paso_sigue_el_avance_de_escalon(
    strategy: Strategy, stage: int, si_gana: int, si_pierde: int
) -> None:
    plan = bankroll_plan(
        strategy, 100, stage, bankroll_current=50_000, bankroll_start=50_000
    )
    assert plan.if_won.stage == si_gana
    assert plan.if_lost.stage == si_pierde


def test_la_plana_pide_lo_mismo_gane_o_pierda() -> None:
    plan = bankroll_plan(
        Strategy.flat, 500, 0, bankroll_current=10_000, bankroll_start=10_000
    )
    assert plan.if_won.suggested_bet == plan.if_lost.suggested_bet == 500


def test_el_siguiente_paso_marca_si_la_banca_ya_no_alcanzaria() -> None:
    """Escalon 4 ($800) con $1.500: perdido, quedan $700 y el 5 pide $1.600."""
    plan = bankroll_plan(
        Strategy.martingale, 100, 3, bankroll_current=1_500, bankroll_start=3_000
    )
    assert plan.if_lost.bankroll_after == 700
    assert plan.if_lost.exceeds_bankroll
    assert not plan.if_won.exceeds_bankroll


def test_el_siguiente_paso_marca_si_la_mesa_no_lo_aceptaria() -> None:
    plan = bankroll_plan(
        Strategy.martingale,
        100,
        5,
        bankroll_current=1_000_000,
        bankroll_start=1_000_000,
        table_limit=5_000,
    )
    # Escalon 7 de la tabla: $6.400, por encima de $5.000.
    assert plan.if_lost.suggested_bet == 6_400
    assert plan.if_lost.exceeds_table_limit


def test_escalones_soportados_desde_el_inicio_coinciden_con_la_tabla() -> None:
    assert stages_supported_from(Strategy.martingale, 100, 0, 102_300) == 10
    assert stages_supported_from(
        Strategy.martingale, 100, 0, 102_300
    ) == max_affordable_stages(Strategy.martingale, 100, 102_300)


def test_escalones_soportados_desde_mitad_de_la_serie() -> None:
    # Desde el escalon 4: $800 + $1.600 = $2.400.
    assert stages_supported_from(Strategy.martingale, 100, 3, 2_400) == 2
    assert stages_supported_from(Strategy.martingale, 100, 3, 2_399) == 1


# ---------- Alertas de banca ----------


def _codigos(alertas: tuple) -> list[str]:
    return [a.code for a in alertas]


def test_sin_alertas_al_empezar_una_plana_con_banca_holgada() -> None:
    assert bankroll_alerts(
        Strategy.flat, 100, 0, bankroll_current=100_000, bankroll_start=100_000
    ) == ()


def test_alerta_critica_si_la_banca_no_cubre_el_escalon() -> None:
    alertas = bankroll_alerts(
        Strategy.martingale, 100, 9, bankroll_current=1_000, bankroll_start=1_000
    )
    assert alertas[0].code == "bankroll_insufficient"
    assert alertas[0].level is AlertLevel.critical
    assert "$51.200" in alertas[0].message


def test_alerta_critica_en_el_ultimo_escalon_que_cubre_la_banca() -> None:
    alertas = bankroll_alerts(
        Strategy.martingale, 100, 3, bankroll_current=1_500, bankroll_start=1_500
    )
    alerta = next(a for a in alertas if a.code == "last_affordable_stage")
    assert alerta.level is AlertLevel.critical


def test_aviso_cuando_quedan_pocos_escalones() -> None:
    alertas = bankroll_alerts(
        Strategy.martingale, 100, 3, bankroll_current=2_400, bankroll_start=2_400
    )
    alerta = next(a for a in alertas if a.code == "few_stages_left")
    assert alerta.level is AlertLevel.caution
    assert "2 escalones" in alerta.message


def test_alerta_critica_si_el_escalon_supera_el_limite_de_mesa() -> None:
    alertas = bankroll_alerts(
        Strategy.martingale,
        100,
        9,
        bankroll_current=1_000_000,
        bankroll_start=1_000_000,
        table_limit=5_000,
    )
    assert "table_limit_exceeded" in _codigos(alertas)
    assert "table_limit_near" not in _codigos(alertas)


@pytest.mark.parametrize(("stage", "distancia"), [(4, 2), (5, 1)])
def test_aviso_cuando_el_limite_de_mesa_esta_cerca(stage: int, distancia: int) -> None:
    """Con tope $5.000, el escalon 7 de la tabla ($6.400) ya no entra."""
    alertas = bankroll_alerts(
        Strategy.martingale,
        100,
        stage,
        bankroll_current=1_000_000,
        bankroll_start=1_000_000,
        table_limit=5_000,
    )
    alerta = next(a for a in alertas if a.code == "table_limit_near")
    assert alerta.level is AlertLevel.caution
    assert f"A {distancia} escal" in alerta.message
    assert "$6.400" in alerta.message


def test_la_plana_nunca_se_acerca_al_limite_de_mesa() -> None:
    alertas = bankroll_alerts(
        Strategy.flat,
        4_000,
        0,
        bankroll_current=1_000_000,
        bankroll_start=1_000_000,
        table_limit=5_000,
    )
    assert "table_limit_near" not in _codigos(alertas)


@pytest.mark.parametrize(
    ("banca", "nivel"),
    [(90_000, None), (70_000, AlertLevel.caution), (40_000, AlertLevel.critical)],
)
def test_alerta_de_perdida_sobre_la_banca_inicial(
    banca: float, nivel: AlertLevel | None
) -> None:
    alertas = bankroll_alerts(
        Strategy.flat, 100, 0, bankroll_current=banca, bankroll_start=100_000
    )
    caida = [a for a in alertas if a.code == "drawdown"]
    if nivel is None:
        assert caida == []
    else:
        assert caida[0].level is nivel
        assert "ventaja de la casa" in caida[0].message


def test_ir_arriba_no_se_presenta_como_haber_vencido_a_la_casa() -> None:
    alertas = bankroll_alerts(
        Strategy.flat, 100, 0, bankroll_current=120_000, bankroll_start=100_000
    )
    alerta = next(a for a in alertas if a.code == "in_profit")
    assert alerta.level is AlertLevel.info
    assert "$20.000" in alerta.message
    assert "no indica" in alerta.message


def test_la_progresion_exponencial_avisa_cuanto_pediria_el_siguiente_escalon() -> None:
    alertas = bankroll_alerts(
        Strategy.martingale, 100, 3, bankroll_current=100_000, bankroll_start=100_000
    )
    alerta = next(a for a in alertas if a.code == "exponential_growth")
    assert "$1.600" in alerta.message


def test_las_alertas_van_de_la_mas_grave_a_la_menos_grave() -> None:
    alertas = bankroll_alerts(
        Strategy.martingale,
        100,
        4,
        bankroll_current=2_000,
        bankroll_start=10_000,
        table_limit=5_000,
    )
    niveles = [a.level for a in alertas]
    orden = {AlertLevel.critical: 0, AlertLevel.caution: 1, AlertLevel.info: 2}
    assert niveles == sorted(niveles, key=orden.__getitem__)
    assert niveles[0] is AlertLevel.critical


def test_las_alertas_nunca_usan_lenguaje_predictivo() -> None:
    prohibidas = ("predic", "va a salir", "seguro", "garantiz", "proximo numero", "le toca")
    escenarios = [
        (Strategy.martingale, 9, 1_000, 1_000, None),
        (Strategy.martingale, 3, 1_500, 10_000, 5_000),
        (Strategy.two_sector_recovery, 4, 20_000, 30_000, 10_000),
        (Strategy.flat, 0, 150_000, 100_000, None),
    ]
    for strategy, stage, banca, inicial, limite in escenarios:
        for alerta in bankroll_alerts(
            strategy,
            100,
            stage,
            bankroll_current=banca,
            bankroll_start=inicial,
            table_limit=limite,
        ):
            texto = alerta.message.lower()
            for palabra in prohibidas:
                assert palabra not in texto, f"{alerta.code} usa {palabra!r}"


# ---------- Limite de perdida del usuario ----------


def test_alerta_critica_al_alcanzar_el_limite_de_perdida() -> None:
    alertas = bankroll_alerts(
        Strategy.flat,
        100,
        0,
        bankroll_current=8_900,
        bankroll_start=10_000,
        loss_limit=1_000,
    )
    alerta = next(a for a in alertas if a.code == "loss_limit_reached")
    assert alerta.level is AlertLevel.critical
    assert "$1.100" in alerta.message
    assert "ventaja de la casa" in alerta.message


def test_avisa_si_el_giro_actual_puede_llevar_al_limite() -> None:
    """Martingala $100: tras $100+$200+$400 perdidos el escalon 4 pide $800 y al
    limite de $1.000 solo le quedan $300."""
    plan = bankroll_plan(
        Strategy.martingale,
        100,
        3,
        bankroll_current=9_300,
        bankroll_start=10_000,
        loss_limit=1_000,
    )
    alerta = next(a for a in plan.alerts if a.code == "loss_limit_next")
    assert alerta.level is AlertLevel.critical
    assert "$300" in alerta.message
    assert plan.if_lost.reaches_loss_limit
    assert not plan.if_won.reaches_loss_limit


def test_avisa_cuando_se_acerca_al_limite() -> None:
    alertas = bankroll_alerts(
        Strategy.flat,
        100,
        0,
        bankroll_current=9_200,
        bankroll_start=10_000,
        loss_limit=1_000,
    )
    alerta = next(a for a in alertas if a.code == "loss_limit_near")
    assert alerta.level is AlertLevel.caution
    assert "$200" in alerta.message


def test_con_limite_propio_no_aparecen_los_umbrales_por_defecto() -> None:
    """40% de caida disparaba el aviso por defecto; con limite de $5.000 manda el del usuario."""
    alertas = bankroll_alerts(
        Strategy.flat,
        100,
        0,
        bankroll_current=6_000,
        bankroll_start=10_000,
        loss_limit=5_000,
    )
    codigos = _codigos(alertas)
    assert "drawdown" not in codigos
    assert "loss_limit_near" in codigos


def test_sin_limite_el_siguiente_paso_nunca_lo_alcanza() -> None:
    plan = bankroll_plan(
        Strategy.martingale, 100, 3, bankroll_current=9_300, bankroll_start=10_000
    )
    assert not plan.if_lost.reaches_loss_limit


def test_las_alertas_del_limite_nunca_usan_lenguaje_predictivo() -> None:
    prohibidas = ("predic", "va a salir", "seguro", "garantiz", "proximo numero", "le toca")
    for banca in (9_900, 9_200, 9_000, 8_000):
        for alerta in bankroll_alerts(
            Strategy.martingale,
            100,
            2,
            bankroll_current=banca,
            bankroll_start=10_000,
            loss_limit=1_000,
        ):
            texto = alerta.message.lower()
            for palabra in prohibidas:
                assert palabra not in texto, f"{alerta.code} usa {palabra!r}"


def test_el_plan_es_una_funcion_pura() -> None:
    kwargs = {"bankroll_current": 5_000, "bankroll_start": 8_000, "table_limit": 3_000}
    assert bankroll_plan(Strategy.martingale, 100, 4, **kwargs) == bankroll_plan(
        Strategy.martingale, 100, 4, **kwargs
    )


# ---------- Gestion aplicada al mercado recomendado (§2.10) ----------
#
# Desde la Fase 3 los sectores los pone el mercado que recomendo el motor, no la
# progresion, y el escalon avanza con el HIT/MISS de la recomendacion.


def test_las_tres_progresiones_de_la_mesa() -> None:
    """La mesa ofrece plana, martingala y recuperacion de dos sectores."""
    assert OFFERED_STRATEGIES == (
        Strategy.flat,
        Strategy.martingale,
        Strategy.two_sector_recovery,
    )


def test_dos_docenas_con_martingala_da_el_monto_por_sector() -> None:
    """El mercado manda: dos docenas son dos sectores aunque la progresion
    elegida sea la martingala, que por si sola cubriria uno."""
    stake = stake_for_market(
        Strategy.martingale,
        100,
        3,
        sectors=2,
        payout=2,
        bankroll_current=100_000,
    )
    assert stake.applicable
    assert stake.sectors == 2
    assert stake.bet_per_sector == 800      # 100 x 2^3, por docena
    assert stake.total_bet == 1_600         # las dos docenas del giro


def test_dos_docenas_con_recuperacion_sigue_la_tabla_verificada() -> None:
    """Tabla del documento verificado, unidad $100: 1-1, 2-2, 6-6, 18-18, 54-54."""
    stakes = [
        stake_for_market(
            Strategy.two_sector_recovery,
            100,
            s,
            sectors=2,
            payout=2,
            bankroll_current=1_000_000,
        )
        for s in range(5)
    ]
    assert [s.bet_per_sector for s in stakes] == [100, 200, 600, 1_800, 5_400]
    assert [s.total_bet for s in stakes] == [200, 400, 1_200, 3_600, 10_800]
    assert [s.cumulative_risked for s in stakes] == [200, 600, 1_800, 5_400, 16_200]


def test_la_recuperacion_de_dos_sectores_no_aplica_a_un_mercado_de_uno() -> None:
    """Su aritmetica asume que el otro sector se pierde y que el acertado paga
    2:1. Sobre "Negro" no describe nada, asi que no se ofrece en vez de dar un
    monto inventado."""
    stake = stake_for_market(
        Strategy.two_sector_recovery,
        100,
        2,
        sectors=1,
        payout=1,
        bankroll_current=100_000,
    )
    assert not stake.applicable
    assert stake.reason is not None
    assert stake.total_bet == 0.0

    assert applies_to_market(Strategy.two_sector_recovery, 2) is None
    assert applies_to_market(Strategy.flat, 1) is None
    assert applies_to_market(Strategy.martingale, 2) is None


def test_la_mesa_devuelve_las_tres_aunque_alguna_no_aplique() -> None:
    stakes = stakes_for_market(
        100,
        {Strategy.flat: 0, Strategy.martingale: 2, Strategy.two_sector_recovery: 1},
        sectors=1,
        payout=1,
        bankroll_current=50_000,
    )
    assert [s.strategy for s in stakes] == list(OFFERED_STRATEGIES)
    assert [s.applicable for s in stakes] == [True, True, False]
    # Cada progresion lleva su propio escalon.
    assert [s.stage for s in stakes] == [0, 2, 1]
    assert stakes[0].total_bet == 100        # plana
    assert stakes[1].total_bet == 400        # martingala, escalon 2


def test_ganar_dos_docenas_en_recuperacion_solo_recupera() -> None:
    """Del escalon 2 en adelante acertar devuelve la serie a cero, no deja
    ganancia: la apuesta por sector es justo lo perdido antes."""
    assert net_if_won_on_market(Strategy.two_sector_recovery, 100, 0, 2, 2) == 100
    for stage in (1, 2, 3, 4):
        assert net_if_won_on_market(Strategy.two_sector_recovery, 100, stage, 2, 2) == 0


def test_no_apostar_no_avanza_la_martingala() -> None:
    """Con NO APOSTAR ninguna progresion se mueve: no hubo serie que continuar."""
    escalones = {
        Strategy.flat: 0,
        Strategy.martingale: 3,
        Strategy.two_sector_recovery: 2,
    }
    todas = frozenset(Strategy)
    assert advance_stages_on_outcome(escalones, hit=None, sectors=1, followed=todas) == escalones
    assert advance_stages_on_outcome(escalones, hit=None, sectors=2, followed=todas) == escalones


def test_sin_apuesta_ninguna_progresion_avanza() -> None:
    """El escalon es el de la serie que el usuario lleva de verdad: si no
    aposto con ninguna gestion, ninguna serie continuo ni se cerro."""
    escalones = {
        Strategy.flat: 0,
        Strategy.martingale: 3,
        Strategy.two_sector_recovery: 2,
    }
    for hit in (True, False):
        assert (
            advance_stages_on_outcome(escalones, hit=hit, sectors=2, followed=frozenset())
            == escalones
        )


def test_solo_avanza_la_gestion_con_la_que_se_aposto() -> None:
    escalones = {
        Strategy.flat: 0,
        Strategy.martingale: 3,
        Strategy.two_sector_recovery: 2,
    }
    solo_martingala = frozenset({Strategy.martingale})
    assert advance_stages_on_outcome(
        escalones, hit=False, sectors=2, followed=solo_martingala
    ) == {
        Strategy.flat: 0,
        Strategy.martingale: 4,
        Strategy.two_sector_recovery: 2,
    }
    assert advance_stages_on_outcome(
        escalones, hit=True, sectors=2, followed=solo_martingala
    ) == {
        Strategy.flat: 0,
        Strategy.martingale: 0,
        Strategy.two_sector_recovery: 2,
    }


def test_dos_sectores_no_se_mueve_sobre_un_mercado_de_un_sector() -> None:
    """Aunque llegue marcada como seguida, una gestion que no aplica al mercado
    no pudo jugarse en ese giro: su escalon queda donde estaba."""
    escalones = {
        Strategy.flat: 0,
        Strategy.martingale: 3,
        Strategy.two_sector_recovery: 2,
    }
    for hit in (True, False):
        resultado = advance_stages_on_outcome(
            escalones, hit=hit, sectors=1, followed=frozenset(Strategy)
        )
        assert resultado[Strategy.two_sector_recovery] == 2


def test_martingala_sobre_el_mercado_respeta_la_tabla_de_102300() -> None:
    """Regresion de la skill: base $100, 10 perdidas seguidas sobre un mercado
    de un sector => $102.300 arriesgados, no $100.000."""
    acumulado = cumulative_risked_on_market(Strategy.martingale, 100, 9, 1)
    assert acumulado == 102_300
    assert acumulado == cumulative_risked(Strategy.martingale, 100, 9)


def test_el_mercado_marca_los_limites_de_banca_y_de_mesa() -> None:
    stake = stake_for_market(
        Strategy.martingale,
        100,
        5,
        sectors=2,
        payout=2,
        bankroll_current=5_000,
        table_limit=1_000,
    )
    assert stake.bet_per_sector == 3_200
    assert stake.total_bet == 6_400
    assert stake.exceeds_bankroll          # 6.400 > 5.000
    assert stake.exceeds_table_limit       # 3.200 por sector > 1.000


# --------------------------------------------------------------------------
# Estado de parar (decidido el 2026-09-24)
# --------------------------------------------------------------------------


def test_con_banca_para_la_apuesta_base_no_hay_que_parar() -> None:
    assert stop_reason(100_000, 100_000, 1_000, None) is None
    # Justo la apuesta base todavia alcanza.
    assert stop_reason(1_000, 100_000, 1_000, None) is None


def test_la_banca_que_no_cubre_la_base_para_la_mesa() -> None:
    assert stop_reason(999.99, 100_000, 1_000, None) is StopReason.bankroll_exhausted
    assert stop_reason(0, 100_000, 1_000, None) is StopReason.bankroll_exhausted


def test_el_redondeo_no_para_la_mesa_antes_de_tiempo() -> None:
    assert stop_reason(999.999999, 100_000, 1_000, None) is None


def test_alcanzar_el_limite_de_perdida_para_la_mesa() -> None:
    assert stop_reason(70_001, 100_000, 1_000, 30_000) is None
    assert stop_reason(70_000, 100_000, 1_000, 30_000) is StopReason.loss_limit_reached
    assert stop_reason(50_000, 100_000, 1_000, 30_000) is StopReason.loss_limit_reached


def test_ir_ganando_no_activa_el_limite() -> None:
    assert stop_reason(150_000, 100_000, 1_000, 30_000) is None


def test_sin_banca_para_la_base_gana_sobre_el_limite() -> None:
    """Si pasan las dos cosas, lo primero que hay que decir es que no queda con
    que apostar."""
    assert stop_reason(500, 100_000, 1_000, 30_000) is StopReason.bankroll_exhausted
