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
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from email.message import EmailMessage as MimeMessage
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 15
SMTP_IMPLICIT_TLS_PORT = 465
#: Las esperas antes de cada reintento de un envio que fallo por algo pasajero.
#: Dos reintentos: en el peor caso son tres timeouts mas siete segundos.
SMTP_RETRY_DELAYS_SECONDS: tuple[float, ...] = (2, 5)


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
        retry_delays: tuple[float, ...] = SMTP_RETRY_DELAYS_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not host:
            raise ValueError("EMAIL_BACKEND=smtp necesita SMTP_HOST")
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.sender = sender
        self.use_tls = use_tls
        self.retry_delays = retry_delays
        self._sleep = sleep

    def send(self, message: EmailMessage) -> None:
        """Envia, y ante un fallo pasajero lo intenta otra vez.

        Un timeout esperando la respuesta al final del envio no dice si el
        servidor se quedo con el correo: el reintento puede hacer que llegue
        dos veces. Para estos correos es mejor eso que no llegue ninguno.
        """
        for delay in self.retry_delays:
            try:
                self._send_once(message)
                return
            except Exception as exc:
                if not _is_transient(exc):
                    raise
                logger.warning(
                    "Fallo pasajero enviando '%s' (%s); se reintenta en %s s",
                    message.subject,
                    type(exc).__name__,
                    delay,
                )
            self._sleep(delay)
        self._send_once(message)

    def _send_once(self, message: EmailMessage) -> None:
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


def _is_transient(exc: Exception) -> bool:
    """El servidor se cayo, no contesto a tiempo o pidio volver despues (4xx).

    Un 5xx (credenciales, destinatario o remitente rechazado) no se arregla
    reintentando.
    """
    if isinstance(exc, smtplib.SMTPResponseException):
        return 400 <= exc.smtp_code < 500
    return isinstance(exc, (smtplib.SMTPServerDisconnected, TimeoutError, ConnectionError))


class EmailDailyLimitReached(RuntimeError):
    """Se alcanzo el tope diario de correos; este no se envio."""


class CappedEmailSender:
    """Corta el envio al llegar a un tope diario de correos.

    Es la ultima barrera si algo (un abuso del registro, un error en un bucle)
    empieza a mandar correo sin control: protege la cuota del proveedor y la
    reputacion del dominio remitente. El tope debe quedar por debajo del limite
    diario del plan contratado.

    La cuenta vive en memoria y por proceso, igual que el rate limit: reiniciar
    la API la pone en cero. El dia se cuenta en UTC.
    """

    def __init__(
        self,
        inner: EmailSender,
        daily_limit: int,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
    ) -> None:
        self.inner = inner
        self.daily_limit = daily_limit
        self._today = today
        self._day: date | None = None
        self._count = 0
        self._lock = threading.Lock()

    def send(self, message: EmailMessage) -> None:
        with self._lock:
            day = self._today()
            if day != self._day:
                self._day, self._count = day, 0
            if self._count >= self.daily_limit:
                raise EmailDailyLimitReached(
                    f"Tope diario de correos alcanzado ({self.daily_limit}): no se envio"
                )
            self._count += 1
        self.inner.send(message)


def build_email_sender(settings: Settings) -> EmailSender:
    sender: EmailSender
    if settings.email_backend == "smtp":
        sender = SmtpEmailSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            user=settings.smtp_user,
            password=settings.smtp_password,
            sender=settings.smtp_from,
            use_tls=settings.smtp_use_tls,
        )
    elif settings.email_backend == "file":
        # Solo para los tests de punta a punta (§5.5). Nunca en produccion.
        sender = FileEmailSender(settings.email_file_dir)
    else:
        sender = ConsoleEmailSender()

    if settings.email_daily_limit > 0:
        return CappedEmailSender(sender, settings.email_daily_limit)
    return sender


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
    except EmailDailyLimitReached as exc:
        # En ERROR para que llegue al monitoreo: alguien tiene que mirar por que
        # se esta enviando tanto correo.
        logger.error("%s (correo '%s')", exc, message.subject)
    except Exception:
        logger.exception("No se pudo enviar el correo '%s'", message.subject)
