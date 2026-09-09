"""Limitador de intentos de login (§3.6).

Implementacion en memoria y por proceso: suficiente para el MVP con un solo
worker, pero NO comparte estado entre procesos ni instancias. Si el despliegue
pasa a varios workers, esto debe moverse a Redis antes de considerarse una
barrera real.
"""

import time
from collections import defaultdict

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 300  # 5 minutos

_attempts: dict[str, list[float]] = defaultdict(list)


def _prune(key: str, now: float) -> list[float]:
    fresh = [t for t in _attempts[key] if now - t < WINDOW_SECONDS]
    _attempts[key] = fresh
    return fresh


def is_rate_limited(key: str) -> bool:
    """True si la clave (ip + correo) supero el maximo en la ventana."""
    return len(_prune(key, time.time())) >= MAX_ATTEMPTS


def register_failure(key: str) -> None:
    now = time.time()
    _prune(key, now)
    _attempts[key].append(now)


def reset(key: str) -> None:
    """Se llama tras un login exitoso."""
    _attempts.pop(key, None)


def reset_all() -> None:
    """Solo para tests."""
    _attempts.clear()
