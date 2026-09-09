"""Resolucion de una apuesta real contra el resultado que salio (§4).

Python puro: sin FastAPI, sin SQLAlchemy, sin red.

Resuelve una apuesta ya ocurrida contra un giro ya ocurrido. No decide que
apostar ni dice nada sobre giros futuros: es aritmetica sobre hechos pasados.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.probability import GameConfig


@dataclass(frozen=True)
class Settlement:
    """Cuanto vuelve y cuanto cambia la banca al resolver una apuesta."""

    won: bool
    #: Total devuelto por la mesa: lo apostado mas la ganancia. Cero si se perdio.
    payout: float
    #: Cambio neto de la banca. Positivo si se gano, `-amount` si se perdio.
    net_change: float


def settle(
    config: GameConfig, category_id: str, group_id: str, amount: float, outcome: str
) -> Settlement:
    """Resuelve la apuesta contra el resultado observado.

    El `payout` de la configuracion es la razon "X a 1": una apuesta de pago 1
    que gana devuelve el doble de lo apostado (lo puesto mas otro tanto), y una
    de pago 2 devuelve el triple. Ganar nunca "devuelve la ganancia sola": la
    banca recupera tambien lo que se puso sobre la mesa.
    """
    if amount <= 0:
        raise ValueError("El monto de la apuesta debe ser positivo")

    category = config.category(category_id)
    if category is None:
        raise KeyError(f"La configuracion no tiene la categoria '{category_id}'")
    group = category.group(group_id)
    if group is None:
        raise KeyError(f"La categoria '{category_id}' no tiene el grupo '{group_id}'")

    if outcome in group.outcomes:
        payout = round(amount * (1 + group.payout), 2)
        return Settlement(won=True, payout=payout, net_change=round(payout - amount, 2))

    return Settlement(won=False, payout=0.0, net_change=round(-amount, 2))
