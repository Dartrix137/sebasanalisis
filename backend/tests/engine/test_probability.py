"""Probabilidad teorica y EV.

Cifras tomadas de la tabla de la skill `motor-estadistico-testing`, que a su vez
viene del documento de estrategia verificado. No inventar valores aqui.
"""

import pytest

from app.engine.probability import (
    GameConfig,
    expected_value,
    straight_probability,
    theoretical_probability,
)

TOLERANCIA = 0.0001  # 0.01 %


# ---------- Tabla de regresion: europea (37) vs. americana (38) ----------


@pytest.mark.parametrize(
    ("categoria", "grupo", "esperada"),
    [
        ("color", "red", 0.4865),
        ("color", "black", 0.4865),
        ("parity", "even", 0.4865),
        ("parity", "odd", 0.4865),
        ("high_low", "low", 0.4865),
        ("high_low", "high", 0.4865),
        ("dozen", "first", 0.3243),
        ("dozen", "second", 0.3243),
        ("dozen", "third", 0.3243),
        ("column", "first", 0.3243),
        ("column", "second", 0.3243),
        ("column", "third", 0.3243),
    ],
)
def test_probabilidades_europea(europea, categoria, grupo, esperada) -> None:
    assert theoretical_probability(europea, categoria, grupo) == pytest.approx(
        esperada, abs=TOLERANCIA
    )


@pytest.mark.parametrize(
    ("categoria", "grupo", "esperada"),
    [
        ("color", "red", 0.4737),
        ("color", "black", 0.4737),
        ("parity", "even", 0.4737),
        ("parity", "odd", 0.4737),
        ("high_low", "low", 0.4737),
        ("high_low", "high", 0.4737),
        ("dozen", "first", 0.3158),
        ("dozen", "second", 0.3158),
        ("dozen", "third", 0.3158),
        ("column", "first", 0.3158),
        ("column", "second", 0.3158),
        ("column", "third", 0.3158),
    ],
)
def test_probabilidades_americana(americana, categoria, grupo, esperada) -> None:
    assert theoretical_probability(americana, categoria, grupo) == pytest.approx(
        esperada, abs=TOLERANCIA
    )


def test_pleno(europea, americana) -> None:
    assert straight_probability(europea) == pytest.approx(0.0270, abs=TOLERANCIA)
    assert straight_probability(americana) == pytest.approx(0.0263, abs=TOLERANCIA)


# ---------- EV ----------


def test_ev_de_toda_apuesta_es_la_ventaja_de_la_casa(europea, americana) -> None:
    """En una mesa sin sesgo, el EV de CUALQUIER apuesta es exactamente
    -1/37 en europea y -1/38 x 2 en americana (§2.1)."""
    for config, edge in ((europea, -1 / 37), (americana, -2 / 38)):
        for categoria in config.categories:
            for grupo in categoria.groups:
                p = theoretical_probability(config, categoria.id, grupo.id)
                assert expected_value(p, grupo.payout) == pytest.approx(edge, abs=1e-9), (
                    f"{categoria.id}.{grupo.id} no da la ventaja de la casa"
                )


def test_ningun_grupo_tiene_ev_positivo(europea, americana) -> None:
    """Un EV positivo generaria una senal permanentemente FUERTE y falsa. Fue el
    caso real del verde americano configurado a 35:1 en vez de 17:1."""
    for config in (europea, americana):
        for categoria in config.categories:
            for grupo in categoria.groups:
                p = theoretical_probability(config, categoria.id, grupo.id)
                assert expected_value(p, grupo.payout) < 0


def test_ev_de_pleno(europea) -> None:
    assert expected_value(straight_probability(europea), 35) == pytest.approx(-1 / 37, abs=1e-9)


# ---------- Estructura generica ----------


def test_el_cero_no_pertenece_a_docena_columna_paridad_ni_alto_bajo(europea) -> None:
    for categoria in ("dozen", "column", "parity", "high_low"):
        assert europea.category(categoria).group_for("0") is None
    # Pero si es verde en la categoria color.
    assert europea.category("color").group_for("0").id == "green"


def test_el_doble_cero_tampoco(americana) -> None:
    for categoria in ("dozen", "column", "parity", "high_low"):
        assert americana.category(categoria).group_for("00") is None
    assert americana.category("color").group_for("00").id == "green"


def test_funciona_con_un_juego_que_no_es_ruleta(dados) -> None:
    """El motor no sabe que existe la ruleta: solo ve categorias y grupos."""
    assert theoretical_probability(dados, "parity", "even") == pytest.approx(6 / 11)
    assert theoretical_probability(dados, "parity", "odd") == pytest.approx(5 / 11)
    assert straight_probability(dados) == pytest.approx(1 / 11)


def test_categoria_o_grupo_inexistente_lanza_error(europea) -> None:
    with pytest.raises(KeyError):
        theoretical_probability(europea, "inexistente", "red")
    with pytest.raises(KeyError):
        theoretical_probability(europea, "color", "morado")


def test_from_dict_usa_el_id_como_label_si_falta() -> None:
    config = GameConfig.from_dict(
        {
            "possible_outcomes": ["1", "2"],
            "categories": [
                {"id": "x", "label": "X", "groups": {"a": {"outcomes": ["1"], "payout": 1}}}
            ],
        }
    )
    assert config.category("x").group("a").label == "a"
    # Y el alpha por defecto es 8 (§2.2).
    assert config.category("x").shrinkage_alpha == 8
