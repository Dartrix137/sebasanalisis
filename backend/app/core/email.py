"""Envio de correo (docs/PLATAFORMA_COMPLETA.md §5.5).

El resto de la aplicacion habla con `EmailSender`, nunca con un proveedor. Cual
implementacion se usa es configuracion (`EMAIL_BACKEND`):

- `smtp`: produccion. SMTP generico; el proveedor (hoy Resend) son solo las
  variables `SMTP_*`.
- `console`: desarrollo. Imprime el correo en el log. Es el valor por defecto.
- `file`: tests de punta a punta. Escribe cada correo como JSON en
  `EMAIL_FILE_DIR`, de donde Playwright lee el enlace.

Los tests de API usan `FakeEmailSender`, que guarda los correos en una lista.
"""

import json
import logging
import smtplib
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.message import EmailMessage as MimeMessage
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 15
SMTP_IMPLICIT_TLS_PORT = 465


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    html: str
    text: str


class EmailSender(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class ConsoleEmailSender:
    """Desarrollo: el correo sale por el log en vez de enviarse."""

    def send(self, message: EmailMessage) -> None:
        logger.info(
            "Correo (no enviado, EMAIL_BACKEND=console)\nPara: %s\nAsunto: %s\n\n%s",
            message.to,
            message.subject,
            message.text,
        )


class FakeEmailSender:
    """Tests: guarda los correos para que el test lea el enlace."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


class FileEmailSender:
    """Tests de punta a punta: un archivo JSON por correo."""

    def __init__(self, directory: str) -> None:
        if not directory:
            raise ValueError("EMAIL_BACKEND=file necesita EMAIL_FILE_DIR")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def send(self, message: EmailMessage) -> None:
        # El prefijo de fecha deja los archivos en orden de envio.
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        path = self.directory / f"{stamp}-{uuid.uuid4().hex[:8]}.json"
        path.write_text(json.dumps(asdict(message), ensure_ascii=False), encoding="utf-8")


class SmtpEmailSender:
    """Produccion: SMTP generico con la libreria estandar."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        sender: str,
        use_tls: bool,
    ) -> None:
        if not host:
            raise ValueError("EMAIL_BACKEND=smtp necesita SMTP_HOST")
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.sender = sender
        self.use_tls = use_tls

    def send(self, message: EmailMessage) -> None:
        mime = MimeMessage()
        mime["From"] = self.sender
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.text)
        mime.add_alternative(message.html, subtype="html")

        # El 465 es TLS desde el primer byte; en los demas puertos (587) la
        # conexion empieza en claro y se cifra con STARTTLS.
        smtp: smtplib.SMTP
        if self.use_tls and self.port == SMTP_IMPLICIT_TLS_PORT:
            smtp = smtplib.SMTP_SSL(self.host, self.port, timeout=SMTP_TIMEOUT_SECONDS)
        else:
            smtp = smtplib.SMTP(self.host, self.port, timeout=SMTP_TIMEOUT_SECONDS)
        with smtp:
            if self.use_tls and self.port != SMTP_IMPLICIT_TLS_PORT:
                smtp.starttls()
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(mime)


def build_email_sender(settings: Settings) -> EmailSender:
    if settings.email_backend == "smtp":
        return SmtpEmailSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            user=settings.smtp_user,
            password=settings.smtp_password,
            sender=settings.smtp_from,
            use_tls=settings.smtp_use_tls,
        )
    if settings.email_backend == "file":
        # Pendiente del paso 5 (§5.5): rechazar este backend en el arranque si
        # hay llaves de produccion de Wompi configuradas.
        return FileEmailSender(settings.email_file_dir)
    return ConsoleEmailSender()


@lru_cache
def get_email_sender() -> EmailSender:
    """Dependencia de FastAPI. Los tests la sustituyen por un `FakeEmailSender`."""
    return build_email_sender(get_settings())


def send_safely(sender: EmailSender, message: EmailMessage) -> None:
    """Envia sin propagar el fallo: va en `BackgroundTasks`, despues de responder.

    Un SMTP caido no puede romper el registro ni el restablecimiento; el usuario
    siempre puede pedir el correo otra vez. El fallo queda en el log (y en el
    monitoreo de errores) sin el contenido del correo, que lleva un enlace de un
    solo uso.
    """
    try:
        sender.send(message)
    except Exception:
        logger.exception("No se pudo enviar el correo '%s'", message.subject)
