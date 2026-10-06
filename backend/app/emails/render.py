"""Arma un correo a partir de su plantilla.

Cada correo tiene dos archivos en `templates/`: `<nombre>.html` y `<nombre>.txt`.
El HTML se renderiza con autoescape: los correos llevan datos del usuario (su
nombre) y no deben poder inyectar marcado. El texto plano no se escapa.

Regla de lenguaje (CLAUDE.md): ningun correo promete resultados ni sugiere que el
producto anticipa un giro. Revisar cada plantilla nueva contra esa regla.
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.email import EmailMessage

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Asunto de cada correo. El nombre es tambien el de sus dos plantillas.
SUBJECTS: dict[str, str] = {
    "verify_email": "Confirma tu correo en Sebasanálisis",
    "reset_password": "Restablece tu contraseña de Sebasanálisis",
    "password_changed": "Tu contraseña de Sebasanálisis cambió",
    "change_email_confirm": "Confirma tu nuevo correo en Sebasanálisis",
    "change_email_notice": "Se pidió cambiar el correo de tu cuenta de Sebasanálisis",
}

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=True),
    # Una variable que falta es un error, no un hueco en blanco en el correo.
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def build_email(name: str, *, to: str, **context: Any) -> EmailMessage:
    """Renderiza el correo `name` para el destinatario `to`."""
    subject = SUBJECTS[name]
    context = {"subject": subject, **context}
    return EmailMessage(
        to=to,
        subject=subject,
        html=_env.get_template(f"{name}.html").render(**context),
        text=_env.get_template(f"{name}.txt").render(**context),
    )
