"""Arma un correo a partir de su plantilla.

Cada correo tiene dos archivos en `templates/`: `<nombre>.html` y `<nombre>.txt`.
El HTML se renderiza con autoescape: los correos llevan datos del usuario (su
nombre) y no deben poder inyectar marcado. El texto plano no se escapa.

Regla de lenguaje (CLAUDE.md): ningun correo promete resultados ni sugiere que el
producto anticipa un giro. Revisar cada plantilla nueva contra esa regla.
"""

from datetime import datetime, timedelta, timezone
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
    "account_deleted": "Tu cuenta de Sebasanálisis fue eliminada",
    "subscription_welcome": "Tu suscripción a Sebasanálisis está activa",
    "payment_receipt": "Recibo de tu pago en Sebasanálisis",
    "renewal_notice": "Aviso: próximo cobro de tu suscripción a Sebasanálisis",
    "period_ending": "Tu acceso a Sebasanálisis está por terminar",
    "payment_failed": "No pudimos cobrar la renovación de tu suscripción a Sebasanálisis",
    "subscription_expired": "Tu suscripción a Sebasanálisis venció",
    "subscription_canceled": "Cancelaste la renovación de tu suscripción a Sebasanálisis",
}

_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
# Las fechas de los correos van en hora de Colombia, que no cambia en el año.
_COLOMBIA = timezone(timedelta(hours=-5))


def format_money(cents: int, currency: str) -> str:
    """`10000000, "COP"` -> `100.000 COP`. Igual que `formatMoney` del frontend."""
    units, rest = divmod(cents, 100)
    whole = f"{units:,}".replace(",", ".")
    return f"{whole},{rest:02d} {currency}" if rest else f"{whole} {currency}"


def format_date(moment: datetime) -> str:
    """`13 de octubre de 2026`, en hora de Colombia."""
    local = moment.astimezone(_COLOMBIA)
    return f"{local.day} de {_MONTHS[local.month - 1]} de {local.year}"

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=True),
    # Una variable que falta es un error, no un hueco en blanco en el correo.
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["money"] = format_money
_env.filters["fecha"] = format_date


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
