"""Parseo y normalizacion de la carga inicial de numeros (§3.5).

Python puro: sin FastAPI, sin SQLAlchemy, sin red.

El usuario escribe o pega la lista de numeros que ya vio en la mesa. Este modulo
la convierte en una secuencia cronologica ascendente lista para persistir. No lee
imagenes ni llama a ningun modelo: el proyecto no integra IA (§3.5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from app.engine.probability import GameConfig


class EntryOrder(str, Enum):
    """Como escribio el usuario la lista.

    Se pregunta siempre y nunca se adivina: el motor pondera por recencia (§2.3),
    asi que invertir el orden en silencio produce un analisis equivocado sin que
    nada falle de forma visible.
    """

    most_recent_first = "most_recent_first"
    most_recent_last = "most_recent_last"


#: Separadores aceptados: coma, punto y coma, espacios y saltos de linea, en
#: cualquier combinacion. Cubre pegar una columna, una fila, o texto suelto.
_SEPARATORS = re.compile(r"[\s,;]+")

#: Tope de numeros por carga. Mas alla de esto no es una sesion de mesa sino una
#: importacion de datos, que es otra funcionalidad.
MAX_BULK_VALUES = 500


def parse_values(raw: str) -> list[str]:
    """Convierte el texto crudo en una lista de valores, en el orden escrito.

    No valida contra la variante ni deduplica: solo separa. Los duplicados se
    conservan a proposito — en la ruleta un mismo numero sale muchas veces y
    quitarlos destruiria la muestra.
    """
    return [token for token in _SEPARATORS.split(raw.strip()) if token]


def to_chronological(values: Sequence[str], order: EntryOrder) -> list[str]:
    """Deja la lista del mas antiguo al mas reciente, que es como se persiste.

    Si el usuario declaro que escribio el mas reciente primero, se invierte.
    """
    ordenados = list(values)
    if order is EntryOrder.most_recent_first:
        ordenados.reverse()
    return ordenados


@dataclass(frozen=True)
class BulkEntryResult:
    """Resultado del parseo, listo para que la capa HTTP decida que hacer."""

    values: list[str]
    invalid_values: list[str]

    @property
    def is_valid(self) -> bool:
        return not self.invalid_values


def prepare_bulk_entry(
    config: GameConfig, raw_values: Sequence[str], order: EntryOrder
) -> BulkEntryResult:
    """Valida contra la variante y normaliza a orden cronologico ascendente.

    Un valor que no pertenece a `possible_outcomes` no se descarta ni se
    "corrige": vuelve en `invalid_values` para que la carga entera se rechace y
    el usuario vea cual escribio mal.
    """
    if len(raw_values) > MAX_BULK_VALUES:
        raise ValueError(
            f"La carga inicial admite hasta {MAX_BULK_VALUES} numeros, "
            f"llegaron {len(raw_values)}"
        )

    posibles = set(config.possible_outcomes)
    invalidos = [v for v in raw_values if v not in posibles]
    if invalidos:
        # Se reportan sin repetir, conservando el orden de aparicion.
        vistos: set[str] = set()
        unicos = [v for v in invalidos if not (v in vistos or vistos.add(v))]
        return BulkEntryResult(values=[], invalid_values=unicos)

    return BulkEntryResult(
        values=to_chronological(raw_values, order), invalid_values=[]
    )
