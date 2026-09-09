"""Validacion de `categories_json` mas alla de lo que cubre Pydantic.

`GameVariantConfig` ya valida la estructura y la regla 3 (outcomes subconjunto de
possible_outcomes). Faltan las reglas 1, 2, 4 y 6 de la skill
`categories-json-validator`, mas la coherencia de los pagos.

Separado de `schemas/` a proposito: los schemas son el contrato de la API y no se
tocan; esto es la barrera de negocio que corre en el endpoint de admin y en el
seed antes de persistir.
"""

from dataclasses import dataclass, field

from app.schemas.games import GameVariantConfig

# Margen para considerar que un EV se desvia de la ventaja de la casa esperada.
EV_TOLERANCE = 1e-6


@dataclass
class ConfigValidationResult:
    """Errores bloquean el guardado; los avisos solo se informan."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_game_config(config: GameVariantConfig) -> ConfigValidationResult:
    result = ConfigValidationResult()
    outcomes = config.possible_outcomes
    total = len(outcomes)

    # Regla 1: sin duplicados en possible_outcomes.
    if len(set(outcomes)) != total:
        dupes = sorted({o for o in outcomes if outcomes.count(o) > 1})
        result.errors.append(f"possible_outcomes tiene valores repetidos: {dupes}")

    # Regla 2: category.id unico.
    ids = [c.id for c in config.categories]
    if len(set(ids)) != len(ids):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        result.errors.append(f"Hay categorias con el mismo id: {dupes}")

    possible = set(outcomes)
    for cat in config.categories:
        covered: set[str] = set()
        for group_id, group in cat.groups.items():
            g_outcomes = group.outcomes
            if len(set(g_outcomes)) != len(g_outcomes):
                result.errors.append(
                    f"Categoria '{cat.id}', grupo '{group_id}': tiene resultados repetidos"
                )
            # Un resultado en dos grupos de la misma categoria haria que las
            # probabilidades de esa categoria sumen mas de 1.
            overlap = covered & set(g_outcomes)
            if overlap:
                result.errors.append(
                    f"Categoria '{cat.id}', grupo '{group_id}': los resultados "
                    f"{sorted(overlap)} ya pertenecen a otro grupo de la misma categoria"
                )
            covered |= set(g_outcomes)

        # Regla 4: cobertura. Que sobren resultados puede ser intencional (el 0
        # fuera de docena en ruleta), pero debe quedar dicho, no asumido.
        uncovered = possible - covered
        if uncovered:
            result.warnings.append(
                f"Categoria '{cat.id}': los resultados {sorted(uncovered)} no pertenecen "
                f"a ningun grupo. Es correcto si es intencional (ej. el 0 en ruleta)"
            )

        # Regla 6: la suma de probabilidades no puede pasarse de 1.
        if total:
            suma = len(covered) / total
            if suma > 1 + EV_TOLERANCE:
                result.errors.append(
                    f"Categoria '{cat.id}': sus grupos suman una probabilidad de {suma:.4f}"
                )

    return result


def group_expected_value(n_outcomes: int, total_outcomes: int, payout: float) -> float:
    """EV = (p x pago) - (1 - p). Ver §2.1."""
    p = n_outcomes / total_outcomes
    return p * payout - (1 - p)


def check_payouts_against_house_edge(
    config: GameVariantConfig, house_edge: float, tolerance: float = 0.005
) -> list[str]:
    """Avisa si algun grupo tiene un EV que no cuadra con la ventaja de la casa.

    En un juego bien configurado el EV de CUALQUIER apuesta es exactamente
    `-house_edge` (§2.1). Un grupo con EV positivo es casi siempre un pago mal
    puesto — el caso real fue el grupo 'green' de la americana con payout 35,
    que daba EV=+0.89 y habria generado una senal permanentemente FUERTE falsa.
    """
    avisos: list[str] = []
    total = len(config.possible_outcomes)
    if not total:
        return avisos
    for cat in config.categories:
        for group_id, group in cat.groups.items():
            ev = group_expected_value(len(group.outcomes), total, group.payout)
            if ev > 0:
                avisos.append(
                    f"Categoria '{cat.id}', grupo '{group_id}': EV = {ev:+.4f}. Un EV positivo "
                    f"no es sostenible en un juego de azar; revisa el pago ({group.payout})"
                )
            elif abs(ev + house_edge) > tolerance:
                avisos.append(
                    f"Categoria '{cat.id}', grupo '{group_id}': EV = {ev:+.4f}, pero la ventaja "
                    f"de la casa declarada es {house_edge:.4f} (se esperaba EV = {-house_edge:+.4f})"
                )
    return avisos
