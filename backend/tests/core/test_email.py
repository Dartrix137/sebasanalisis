"""Envio de correo y plantillas (§5.5). Sin red ni base."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.core import email as email_module
from app.core.config import Settings
from app.core.email import (
    ConsoleEmailSender,
    EmailMessage,
    FakeEmailSender,
    FileEmailSender,
    SmtpEmailSender,
    build_email_sender,
    send_safely,
)
from app.emails import build_email
from app.emails.render import SUBJECTS, TEMPLATES_DIR

MESSAGE = EmailMessage(to="ana@ejemplo.com", subject="Asunto", html="<p>hola</p>", text="hola")

# Contexto suficiente para renderizar cualquiera de las plantillas.
CONTEXT: dict[str, Any] = {
    "display_name": "Ana",
    "url": "https://sebasanalisis.com/verificar-correo?token=abc",
    "forgot_url": "https://sebasanalisis.com/olvide-contrasena",
    "new_email": "nuevo@ejemplo.com",
    "hours": 48,
    "minutes": 60,
}

# Regla de producto no negociable (CLAUDE.md): ningun correo suena predictivo.
PROHIBIDAS = (
    "predice",
    "va a salir",
    "seguro",
    "garantiza",
    "infalible",
    "ventaja",
)


# ---------- Plantillas ----------


@pytest.mark.parametrize("name", sorted(SUBJECTS))
def test_cada_correo_tiene_html_y_texto_con_el_pie_legal(name: str) -> None:
    message = build_email(name, to="ana@ejemplo.com", **CONTEXT)

    assert message.to == "ana@ejemplo.com"
    assert message.subject == SUBJECTS[name]
    assert "<html" in message.html
    assert "<" not in message.text.replace("<br>", "")
    for cuerpo in (message.html, message.text):
        assert "no son una predicción" in cuerpo
        assert "No recibe apuestas" in cuerpo


@pytest.mark.parametrize("name", sorted(SUBJECTS))
def test_ningun_correo_usa_lenguaje_predictivo(name: str) -> None:
    message = build_email(name, to="ana@ejemplo.com", **CONTEXT)
    # La unica mencion permitida es la negacion del pie: "no son una predicción".
    texto = (message.subject + " " + message.text).lower().replace("no son una predicción", "")
    assert "predicci" not in texto
    for palabra in PROHIBIDAS:
        assert palabra not in texto, f"'{palabra}' en el correo {name}"


def test_cada_plantilla_tiene_su_asunto_y_sus_dos_archivos() -> None:
    en_disco = {
        p.stem for p in TEMPLATES_DIR.iterdir() if not p.name.startswith(("base", "_"))
    }
    assert en_disco == set(SUBJECTS)
    for name in SUBJECTS:
        assert (TEMPLATES_DIR / f"{name}.html").is_file()
        assert (TEMPLATES_DIR / f"{name}.txt").is_file()


def test_el_html_escapa_los_datos_del_usuario() -> None:
    contexto = {**CONTEXT, "display_name": '<script>alert("x")</script>'}
    message = build_email("verify_email", to="ana@ejemplo.com", **contexto)

    assert "<script>" not in message.html
    assert "&lt;script&gt;" in message.html
    # El texto plano no interpreta marcado: va tal cual.
    assert '<script>alert("x")</script>' in message.text


def test_el_enlace_viaja_en_los_dos_cuerpos() -> None:
    message = build_email("reset_password", to="ana@ejemplo.com", **CONTEXT)
    assert CONTEXT["url"] in message.text
    assert 'href="https://sebasanalisis.com/verificar-correo?token=abc"' in message.html


def test_sin_nombre_el_saludo_no_queda_roto() -> None:
    message = build_email("verify_email", to="ana@ejemplo.com", **{**CONTEXT, "display_name": None})
    assert message.text.lstrip().startswith("Hola:")


def test_una_variable_que_falta_es_un_error() -> None:
    with pytest.raises(Exception, match="url"):
        build_email("verify_email", to="ana@ejemplo.com", display_name="Ana", hours=48)


# ---------- Senders ----------


def test_fake_guarda_los_correos() -> None:
    sender = FakeEmailSender()
    sender.send(MESSAGE)
    assert sender.sent == [MESSAGE]


def test_file_escribe_un_json_por_correo(tmp_path: Path) -> None:
    sender = FileEmailSender(str(tmp_path / "correos"))
    sender.send(MESSAGE)
    sender.send(MESSAGE)

    archivos = sorted((tmp_path / "correos").glob("*.json"))
    assert len(archivos) == 2
    assert json.loads(archivos[0].read_text(encoding="utf-8")) == {
        "to": "ana@ejemplo.com",
        "subject": "Asunto",
        "html": "<p>hola</p>",
        "text": "hola",
    }


def test_file_sin_carpeta_se_rechaza() -> None:
    with pytest.raises(ValueError, match="EMAIL_FILE_DIR"):
        FileEmailSender("")


def test_console_no_envia_nada(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger="app.core.email"):
        ConsoleEmailSender().send(MESSAGE)
    assert "ana@ejemplo.com" in caplog.text
    assert "hola" in caplog.text


class _FakeSmtp:
    """Sustituto de smtplib.SMTP que anota lo que se le pide."""

    instances: list["_FakeSmtp"] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.calls: list[str] = []
        self.sent: list[Any] = []
        _FakeSmtp.instances.append(self)

    def __enter__(self) -> "_FakeSmtp":
        return self

    def __exit__(self, *exc: object) -> None:
        self.calls.append("quit")

    def starttls(self) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login:{user}")

    def send_message(self, mime: Any) -> None:
        self.sent.append(mime)
        self.calls.append("send")


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[_FakeSmtp]:
    _FakeSmtp.instances = []
    monkeypatch.setattr(email_module.smtplib, "SMTP", _FakeSmtp)
    monkeypatch.setattr(email_module.smtplib, "SMTP_SSL", _FakeSmtp)
    return _FakeSmtp


def _smtp(port: int = 587, use_tls: bool = True) -> SmtpEmailSender:
    return SmtpEmailSender(
        host="smtp.ejemplo.com",
        port=port,
        user="usuario",
        password="clave",
        sender="Sebasanálisis <no-responder@ejemplo.com>",
        use_tls=use_tls,
    )


def test_smtp_cifra_se_autentica_y_envia_las_dos_versiones(fake_smtp: type[_FakeSmtp]) -> None:
    _smtp().send(MESSAGE)

    (conexion,) = fake_smtp.instances
    assert (conexion.host, conexion.port) == ("smtp.ejemplo.com", 587)
    assert conexion.timeout > 0, "toda conexion SMTP lleva timeout"
    assert conexion.calls == ["starttls", "login:usuario", "send", "quit"]

    (mime,) = conexion.sent
    assert mime["To"] == "ana@ejemplo.com"
    assert mime["Subject"] == "Asunto"
    assert "no-responder@ejemplo.com" in mime["From"]
    tipos = [parte.get_content_type() for parte in mime.iter_parts()]
    assert tipos == ["text/plain", "text/html"]


def test_smtp_en_el_465_no_hace_starttls(fake_smtp: type[_FakeSmtp]) -> None:
    """El 465 ya es TLS desde el primer byte: pedir STARTTLS encima falla."""
    _smtp(port=465).send(MESSAGE)
    assert fake_smtp.instances[0].calls == ["login:usuario", "send", "quit"]


def test_smtp_sin_host_se_rechaza() -> None:
    with pytest.raises(ValueError, match="SMTP_HOST"):
        SmtpEmailSender(host="", port=587, user="", password="", sender="x", use_tls=True)


# ---------- Seleccion por configuracion ----------


def test_el_backend_por_defecto_es_la_consola() -> None:
    assert isinstance(build_email_sender(Settings(_env_file=None)), ConsoleEmailSender)


def test_el_backend_sale_de_la_configuracion(tmp_path: Path) -> None:
    smtp = build_email_sender(
        Settings(_env_file=None, email_backend="smtp", smtp_host="smtp.ejemplo.com")
    )
    archivo = build_email_sender(
        Settings(_env_file=None, email_backend="file", email_file_dir=str(tmp_path))
    )
    assert isinstance(smtp, SmtpEmailSender)
    assert isinstance(archivo, FileEmailSender)


# ---------- Envio que no rompe la peticion ----------


class _Roto:
    def send(self, message: EmailMessage) -> None:
        raise ConnectionError("SMTP caido")


def test_un_fallo_de_envio_se_registra_y_no_se_propaga(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("ERROR", logger="app.core.email"):
        send_safely(_Roto(), MESSAGE)

    assert "No se pudo enviar el correo 'Asunto'" in caplog.text
    # El cuerpo lleva un enlace de un solo uso: no va al log.
    assert "hola" not in caplog.text.replace("No se pudo", "")
