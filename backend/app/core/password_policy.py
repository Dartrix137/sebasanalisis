"""Politica minima de contrasenas (§5.3 de la Fase 4).

Diez caracteres como minimo, y se rechazan las mas comunes con una lista local:
no se consulta ningun servicio externo. Aplica a toda contrasena NUEVA
(registro, restablecimiento, cambio); las cuentas que ya existen siguen
entrando con la suya.
"""

from functools import lru_cache
from pathlib import Path

MIN_LENGTH = 10
# argon2 no trunca, pero un limite evita que alguien mande megabytes a hashear.
MAX_LENGTH = 200

_COMMON_PASSWORDS_FILE = Path(__file__).with_name("common_passwords.txt")


class PasswordPolicyError(ValueError):
    """La contrasena no cumple la politica. El mensaje es para el usuario."""


@lru_cache
def _common_passwords() -> frozenset[str]:
    lines = _COMMON_PASSWORDS_FILE.read_text(encoding="utf-8").splitlines()
    return frozenset(
        line.strip().lower() for line in lines if line.strip() and not line.startswith("#")
    )


def _is_trivial_sequence(password: str) -> bool:
    """Un solo caracter repetido, o una escalera de caracteres consecutivos."""
    if len(set(password)) == 1:
        return True
    steps = {ord(b) - ord(a) for a, b in zip(password, password[1:], strict=False)}
    return steps in ({1}, {-1})


def validate_password(password: str, *, email: str | None = None) -> None:
    """Lanza `PasswordPolicyError` si la contrasena no se puede aceptar."""
    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(f"La contraseña debe tener al menos {MIN_LENGTH} caracteres")
    if len(password) > MAX_LENGTH:
        raise PasswordPolicyError(f"La contraseña no puede pasar de {MAX_LENGTH} caracteres")

    lowered = password.lower()
    if lowered in _common_passwords() or _is_trivial_sequence(lowered):
        raise PasswordPolicyError(
            "Esa contraseña es demasiado común y fácil de adivinar. Elige otra"
        )
    if email and lowered == email.lower():
        raise PasswordPolicyError("La contraseña no puede ser tu correo")
