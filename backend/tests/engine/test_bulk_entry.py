"""Carga inicial de numeros: parseo, orden y validacion (§3.5)."""

import pytest

from app.engine.bulk_entry import (
    MAX_BULK_VALUES,
    EntryOrder,
    parse_values,
    prepare_bulk_entry,
    to_chronological,
)
from app.engine.probability import GameConfig

RULETA_MINI = {
    "possible_outcomes": ["0", "1", "2", "3", "4", "5", "6"],
    "categories": [
        {
            "id": "color",
            "label": "Color",
            "shrinkage_alpha": 8,
            "groups": {
                "red": {"label": "Rojo", "outcomes": ["1", "3", "5"], "payout": 1},
                "black": {"label": "Negro", "outcomes": ["2", "4", "6"], "payout": 1},
                "green": {"label": "Verde", "outcomes": ["0"], "payout": 6},
            },
        }
    ],
}


@pytest.fixture
def config() -> GameConfig:
    return GameConfig.from_dict(RULETA_MINI)


# ---------- Parseo tolerante ----------


@pytest.mark.parametrize(
    "crudo",
    [
        "1,2,3",
        "1 2 3",
        "1\n2\n3",
        "1;2;3",
        "  1 , 2 ,   3  ",
        "1,,2,,,3",
        "1\n\n2\t3",
        "1, 2\n3;",
    ],
)
def test_acepta_cualquier_combinacion_de_separadores(crudo: str) -> None:
    assert parse_values(crudo) == ["1", "2", "3"]


def test_texto_vacio_no_da_valores() -> None:
    assert parse_values("") == []
    assert parse_values("   \n  ") == []


def test_conserva_los_duplicados() -> None:
    """Quitar repeticiones destruiria la muestra: en la ruleta se repiten."""
    assert parse_values("7 7 7") == ["7", "7", "7"]


def test_conserva_el_orden_escrito() -> None:
    assert parse_values("3 1 2") == ["3", "1", "2"]


def test_no_toca_valores_de_dos_caracteres() -> None:
    """La americana tiene '00': separar por caracteres lo romperia."""
    assert parse_values("00, 0, 13") == ["00", "0", "13"]


# ---------- Orden ----------


def test_mas_reciente_primero_se_invierte() -> None:
    """Se persiste siempre del mas antiguo al mas reciente (§3.5)."""
    escrito = ["5", "4", "3"]  # 5 fue el ultimo que salio
    assert to_chronological(escrito, EntryOrder.most_recent_first) == ["3", "4", "5"]


def test_mas_reciente_al_final_se_deja_igual() -> None:
    escrito = ["3", "4", "5"]
    assert to_chronological(escrito, EntryOrder.most_recent_last) == ["3", "4", "5"]


def test_el_orden_no_muta_la_lista_original() -> None:
    original = ["1", "2", "3"]
    to_chronological(original, EntryOrder.most_recent_first)
    assert original == ["1", "2", "3"]


# ---------- Validacion contra la variante ----------


def test_carga_valida_queda_en_orden_cronologico(config: GameConfig) -> None:
    r = prepare_bulk_entry(config, ["5", "4", "3"], EntryOrder.most_recent_first)
    assert r.is_valid
    assert r.values == ["3", "4", "5"]


def test_un_valor_ajeno_a_la_variante_rechaza_la_carga_entera(
    config: GameConfig,
) -> None:
    """No se descarta en silencio ni se 'corrige': se rechaza y se informa."""
    r = prepare_bulk_entry(config, ["1", "37", "2"], EntryOrder.most_recent_last)
    assert not r.is_valid
    assert r.invalid_values == ["37"]
    assert r.values == []


def test_los_invalidos_se_reportan_sin_repetir(config: GameConfig) -> None:
    r = prepare_bulk_entry(config, ["9", "1", "9", "8"], EntryOrder.most_recent_last)
    assert r.invalid_values == ["9", "8"]


def test_los_duplicados_validos_se_conservan(config: GameConfig) -> None:
    r = prepare_bulk_entry(config, ["3", "3", "3"], EntryOrder.most_recent_last)
    assert r.is_valid
    assert r.values == ["3", "3", "3"]


def test_carga_vacia_es_valida(config: GameConfig) -> None:
    """Abrir la sesion sin historial previo es un caso normal."""
    r = prepare_bulk_entry(config, [], EntryOrder.most_recent_last)
    assert r.is_valid
    assert r.values == []


def test_se_rechaza_una_carga_desmedida(config: GameConfig) -> None:
    with pytest.raises(ValueError):
        prepare_bulk_entry(
            config, ["1"] * (MAX_BULK_VALUES + 1), EntryOrder.most_recent_last
        )


def test_el_tope_exacto_se_acepta(config: GameConfig) -> None:
    r = prepare_bulk_entry(config, ["1"] * MAX_BULK_VALUES, EntryOrder.most_recent_last)
    assert r.is_valid
    assert len(r.values) == MAX_BULK_VALUES


# ---------- Pureza ----------


def test_es_una_funcion_pura(config: GameConfig) -> None:
    a = prepare_bulk_entry(config, ["1", "2"], EntryOrder.most_recent_first)
    b = prepare_bulk_entry(config, ["1", "2"], EntryOrder.most_recent_first)
    assert a == b


def test_sirve_a_un_juego_que_no_es_ruleta() -> None:
    """El parseo es generico: no sabe que existe la ruleta."""
    dado = GameConfig.from_dict(
        {
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
                }
            ],
        }
    )
    r = prepare_bulk_entry(dado, parse_values("6 5 4"), EntryOrder.most_recent_first)
    assert r.values == ["4", "5", "6"]
