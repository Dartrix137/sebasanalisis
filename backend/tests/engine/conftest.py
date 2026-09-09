"""Fixtures del motor: configuraciones planas, sin base de datos ni red.

Las de ruleta se leen del mismo `seed_data/` que carga el seed, para que los
tests fallen si alguien cambia el JSON sembrado sin querer.
"""

import json
from pathlib import Path

import pytest

from app.engine.probability import GameConfig

SEED_DATA = Path(__file__).resolve().parents[2] / "app" / "db" / "seed_data"


def _load(nombre: str) -> GameConfig:
    raw = json.loads((SEED_DATA / nombre).read_text(encoding="utf-8"))
    return GameConfig.from_dict(raw)


@pytest.fixture(scope="session")
def europea() -> GameConfig:
    return _load("roulette_european.json")


@pytest.fixture(scope="session")
def americana() -> GameConfig:
    return _load("roulette_american.json")


@pytest.fixture(scope="session")
def dados() -> GameConfig:
    """Juego que no es ruleta, para comprobar que el motor no la tiene hardcodeada."""
    return GameConfig.from_dict(
        {
            "possible_outcomes": [str(n) for n in range(2, 13)],
            "categories": [
                {
                    "id": "parity",
                    "label": "Par/Impar",
                    "shrinkage_alpha": 8,
                    "groups": {
                        "even": {
                            "label": "Par",
                            "outcomes": ["2", "4", "6", "8", "10", "12"],
                            "payout": 1,
                        },
                        "odd": {
                            "label": "Impar",
                            "outcomes": ["3", "5", "7", "9", "11"],
                            "payout": 1,
                        },
                    },
                }
            ],
        }
    )
