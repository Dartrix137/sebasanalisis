"""Limitador de intentos (§3.6 del doc de arquitectura, §5.6 de la Fase 4).

Implementacion en memoria y por proceso: sirve mientras la API corra con un solo
worker, pero NO comparte estado entre procesos ni replicas. Si el despliegue pasa
a varios workers, esto se mueve a una tabla de Postgres antes de considerarse una
barrera real (no se agrega Redis solo para esto, §13.5).

Dos formas de uso:

- Login: solo cuentan los intentos FALLIDOS (`is_rate_limited`,
  `register_failure`, `reset`), y un login correcto limpia la cuenta.
- El resto de endpoints sensibles: cuenta cada intento (`hit`).
"""

import time
from collections import defaultdict

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 300  # 5 minutos

_attempts: dict[str, list[float]] = defaultdict(list)


def _prune(key: str, now: float, window: float = WINDOW_SECONDS) -> list[float]:
    fresh = [t for t in _attempts[key] if now - t < window]
    _attempts[key] = fresh
    return fresh


def is_rate_limited(key: str) -> bool:
    """True si la clave (ip + correo) supero el maximo en la ventana."""
    return len(_prune(key, time.time())) >= MAX_ATTEMPTS


def register_failure(key: str, window: float = WINDOW_SECONDS) -> None:
    now = time.time()
    _prune(key, now, window)
    _attempts[key].append(now)


def failures(key: str, window: float) -> int:
    """Cuantos fallos lleva la clave dentro de la ventana."""
    return len(_prune(key, time.time(), window))


def reset(key: str) -> None:
    """Se llama tras un login exitoso."""
    _attempts.pop(key, None)


def hit(key: str, *, limit: int, window: float) -> bool:
    """Anota un intento y dice si se permite.

    Devuelve False cuando la clave ya habia llegado a `limit` intentos dentro de
    la ventana. Un intento rechazado no se anota: seguir insistiendo no alarga el
    bloqueo, que termina cuando el intento mas viejo sale de la ventana.
    """
    now = time.time()
    fresh = _prune(key, now, window)
    if len(fresh) >= limit:
        return False
    fresh.append(now)
    return True


def reset_all() -> None:
    """Solo para tests."""
    _attempts.clear()
