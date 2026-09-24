"""Probabilidad teorica y estructura generica de juego.

Python puro: sin FastAPI, sin SQLAlchemy, sin red. Este modulo define las
estructuras con las que trabaja todo el motor y nunca sabe que "docena" o
"color" son cosas de ruleta — solo ve categorias y grupos leidos de
`game_variants.categories_json` (§3.2).

Las estructuras son propias del motor y no los schemas de Pydantic a proposito:
asi el motor se puede testear con diccionarios planos y no arrastra el contrato
de la API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class Group:
    """Un grupo dentro de una categoria, ej. 'red' dentro de 'color'."""

    id: str
    label: str
    outcomes: frozenset[str]
    payout: float
    #: Si el grupo entra al catalogo de mercados del motor de recomendacion
    #: (§2.10). Por defecto si. El verde de la ruleta lo pone en False: cubre el
    #: 0/00 y no es una de las zonas que el producto recomienda, pero se sigue
    #: necesitando como grupo para que las frecuencias de `color` sumen 1 y para
    #: que el chi-cuadrado tenga todas sus celdas.
    #:
    #: Es configuracion del juego y no una regla del motor: un juego nuevo que
    #: no declare nada tiene todos sus grupos como mercados.
    market: bool = True


@dataclass(frozen=True)
class Category:
    id: str
    label: str
    shrinkage_alpha: float
    groups: tuple[Group, ...]

    def group(self, group_id: str) -> Group | None:
        return next((g for g in self.groups if g.id == group_id), None)

    def group_for(self, outcome: str) -> Group | None:
        """Grupo al que pertenece un resultado, o None si no pertenece a ninguno.

        None es un caso legitimo y frecuente: el 0 no esta en ninguna docena.
        """
        return next((g for g in self.groups if outcome in g.outcomes), None)

    @property
    def covered_outcomes(self) -> frozenset[str]:
        return frozenset().union(*(g.outcomes for g in self.groups)) if self.groups else frozenset()


@dataclass(frozen=True)
class AllowedCombination:
    """Una apuesta a varios grupos de la misma categoria a la vez.

    Existe en los datos y no en el motor porque "dos docenas" es una regla de la
    mesa, no una verdad matematica: un juego nuevo declara las suyas y el motor
    no cambia (§2.10).
    """

    id: str
    label: str
    category_id: str
    group_ids: tuple[str, ...]


#: Umbral de `signal_score` a partir del cual el motor recomienda apostar,
#: cuando la variante no declara el suyo (§2.10).
DEFAULT_RECOMMENDATION_THRESHOLD = 50.0


@dataclass(frozen=True)
class GameConfig:
    possible_outcomes: tuple[str, ...]
    categories: tuple[Category, ...]
    #: Combinaciones permitidas, en el orden declarado. Es una lista y no un
    #: diccionario a proposito: JSONB no conserva el orden de las claves de un
    #: objeto, y el desempate del motor necesita un orden de catalogo estable.
    allowed_combinations: tuple[AllowedCombination, ...] = ()
    recommendation_threshold: float = DEFAULT_RECOMMENDATION_THRESHOLD

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> GameConfig:
        """Construye la configuracion desde el `categories_json` crudo."""
        categorias = []
        for cat in raw["categories"]:
            grupos = tuple(
                Group(
                    id=gid,
                    label=g.get("label") or gid,
                    outcomes=frozenset(g["outcomes"]),
                    payout=float(g["payout"]),
                    market=bool(g.get("market", True)),
                )
                for gid, g in cat["groups"].items()
            )
            categorias.append(
                Category(
                    id=cat["id"],
                    label=cat["label"],
                    shrinkage_alpha=float(cat.get("shrinkage_alpha", 8)),
                    groups=grupos,
                )
            )
        combinaciones = tuple(
            AllowedCombination(
                id=c["id"],
                label=c.get("label") or c["id"],
                category_id=c["category_id"],
                group_ids=tuple(c["group_ids"]),
            )
            for c in raw.get("allowed_combinations", [])
        )
        return cls(
            possible_outcomes=tuple(raw["possible_outcomes"]),
            categories=tuple(categorias),
            allowed_combinations=combinaciones,
            recommendation_threshold=float(
                raw.get("recommendation_threshold", DEFAULT_RECOMMENDATION_THRESHOLD)
            ),
        )

    def category_index(self, category_id: str) -> int:
        """Posicion de la categoria en el orden declarado.

        Es parte del desempate del motor (§2.10): `categories` es un array JSON,
        asi que su orden sobrevive a JSONB, al contrario que el de `groups`.
        """
        return next(
            (i for i, c in enumerate(self.categories) if c.id == category_id),
            len(self.categories),
        )

    @property
    def total_outcomes(self) -> int:
        return len(self.possible_outcomes)

    def category(self, category_id: str) -> Category | None:
        return next((c for c in self.categories if c.id == category_id), None)


def theoretical_probability(config: GameConfig, category_id: str, group_id: str) -> float:
    """Probabilidad teorica constante de un grupo: cuantos resultados cubre
    sobre el total de resultados posibles.

    Nunca cambia con el historial de la sesion. Es la referencia contra la que se
    compara toda frecuencia observada (§2.1).
    """
    category = config.category(category_id)
    if category is None:
        raise KeyError(f"La configuracion no tiene la categoria '{category_id}'")
    group = category.group(group_id)
    if group is None:
        raise KeyError(f"La categoria '{category_id}' no tiene el grupo '{group_id}'")
    if config.total_outcomes == 0:
        raise ValueError("La configuracion no tiene resultados posibles")
    return len(group.outcomes) / config.total_outcomes


def combined_probability(
    config: GameConfig, selections: Sequence[tuple[str, str]]
) -> float:
    """Probabilidad teorica de cubrir varios grupos a la vez, como al apostar a
    dos docenas.

    Exige que los grupos sean disjuntos: si se solaparan, sumar sus
    probabilidades contaria dos veces los resultados compartidos y daria un
    numero mas alto que la cobertura real.
    """
    if not selections:
        raise ValueError("Hay que seleccionar al menos un grupo")

    cubiertos: set[str] = set()
    for category_id, group_id in selections:
        category = config.category(category_id)
        if category is None:
            raise KeyError(f"La configuracion no tiene la categoria '{category_id}'")
        group = category.group(group_id)
        if group is None:
            raise KeyError(f"La categoria '{category_id}' no tiene el grupo '{group_id}'")
        if cubiertos & group.outcomes:
            raise ValueError(
                f"El grupo '{group_id}' se solapa con otro ya seleccionado: "
                "sumar sus probabilidades contaria resultados dos veces"
            )
        cubiertos |= group.outcomes

    if config.total_outcomes == 0:
        raise ValueError("La configuracion no tiene resultados posibles")
    return len(cubiertos) / config.total_outcomes


def straight_probability(config: GameConfig) -> float:
    """Probabilidad de un resultado individual (pleno en ruleta): 1/N.

    No necesita una categoria con 37 grupos: se deriva del total de resultados.
    """
    if config.total_outcomes == 0:
        raise ValueError("La configuracion no tiene resultados posibles")
    return 1 / config.total_outcomes


def expected_value(probability: float, payout: float) -> float:
    """EV = (p x pago) - (1 - p)  (§2.1).

    Con `probability` igual a la teorica, da exactamente menos la ventaja de la
    casa. Cuando se pasa la frecuencia observada con shrinkage, el resultado es
    una lectura sobre la muestra, no una garantia sobre giros futuros.
    """
    return probability * payout - (1 - probability)


def group_for_outcome(config: GameConfig, category_id: str, outcome: str) -> Group | None:
    category = config.category(category_id)
    return category.group_for(outcome) if category else None
