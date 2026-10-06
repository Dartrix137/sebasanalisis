"""Verificacion de correo, contrasena, sesiones y cuenta (Fase 4, paso 1, §5).

Los casos de aceptacion de §5.8 estan marcados con "§5.8" en su docstring.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.email import EmailMessage
from app.core.user_tokens import hash_token
from app.models import User, UserToken

PASSWORD = "clave-segura-123"
NEW_PASSWORD = "otra-clave-distinta-456"


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@ejemplo.com"


def _register(client: TestClient, email: str | None = None, **extra: str) -> dict:
    r = client.post(
        "/auth/register", json={"email": email or _email(), "password": PASSWORD, **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()


def _auth(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _token_in(message: EmailMessage) -> str:
    """El token de un solo uso, leido del enlace del correo como lo haria el usuario."""
    match = re.search(r"[?&]token=([A-Za-z0-9_-]+)", message.text)
    assert match, f"el correo no trae enlace con token:\n{message.text}"
    return match.group(1)


def _last(outbox: list[EmailMessage], subject_part: str) -> EmailMessage:
    found = [m for m in outbox if subject_part in m.subject]
    assert found, f"no se envio ningun correo con '{subject_part}': {[m.subject for m in outbox]}"
    return found[-1]


# ---------- Verificacion del correo (§5.2) ----------


def test_registrarse_envia_el_correo_de_verificacion(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    tokens = _register(client, display_name="Ana")

    assert tokens["user"]["email_verified"] is False
    (correo,) = outbox
    assert correo.to == tokens["user"]["email"]
    assert "Confirma tu correo" in correo.subject
    assert "/verificar-correo?token=" in correo.text
    assert "Hola Ana" in correo.text


def test_verificar_el_correo_marca_la_cuenta(
    client: TestClient, outbox: list[EmailMessage], db: Session
) -> None:
    tokens = _register(client)

    r = client.post("/auth/verify-email", json={"token": _token_in(outbox[0])})
    assert r.status_code == 200, r.text

    me = client.get("/auth/me", headers=_auth(tokens)).json()
    assert me["email_verified"] is True
    user = db.scalar(select(User).where(User.email == me["email"]))
    assert user is not None and user.email_verified_at is not None


def test_token_de_verificacion_usado_dos_veces_se_rechaza(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    """§5.8: el segundo uso del mismo enlace se rechaza."""
    _register(client)
    token = _token_in(outbox[0])

    assert client.post("/auth/verify-email", json={"token": token}).status_code == 200
    segundo = client.post("/auth/verify-email", json={"token": token})
    assert segundo.status_code == 400
    assert "enlace" in segundo.json()["detail"]


def test_token_vencido_se_rechaza(
    client: TestClient, outbox: list[EmailMessage], db: Session
) -> None:
    """§5.8: un token vencido no verifica nada."""
    tokens = _register(client)
    token = _token_in(outbox[0])
    db.execute(
        text("UPDATE user_tokens SET expires_at = :t WHERE token_hash = :h"),
        {"t": datetime.now(UTC) - timedelta(seconds=1), "h": hash_token(token)},
    )
    db.commit()

    assert client.post("/auth/verify-email", json={"token": token}).status_code == 400
    assert client.get("/auth/me", headers=_auth(tokens)).json()["email_verified"] is False


def test_un_token_inventado_se_rechaza(client: TestClient) -> None:
    r = client.post("/auth/verify-email", json={"token": "no-existe-este-token"})
    assert r.status_code == 400


def test_en_la_base_nunca_aparece_un_token_en_claro(
    client: TestClient, outbox: list[EmailMessage], db: Session
) -> None:
    """§5.8: la tabla guarda el SHA-256, no el token."""
    tokens = _register(client)
    client.post("/auth/forgot-password", json={"email": tokens["user"]["email"]})
    en_claro = {_token_in(m) for m in outbox}
    assert len(en_claro) == 2

    filas = db.scalars(
        select(UserToken).where(UserToken.user_id == uuid.UUID(tokens["user"]["id"]))
    ).all()
    assert len(filas) == 2
    for fila in filas:
        assert fila.token_hash not in en_claro
        assert re.fullmatch(r"[0-9a-f]{64}", fila.token_hash)
    assert {f.token_hash for f in filas} == {hash_token(t) for t in en_claro}

    volcado = str(db.execute(text("SELECT * FROM user_tokens")).all())
    for token in en_claro:
        assert token not in volcado


def test_reenviar_la_verificacion_invalida_el_enlace_anterior(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    tokens = _register(client)
    viejo = _token_in(outbox[0])

    r = client.post("/auth/resend-verification", headers=_auth(tokens))
    assert r.status_code == 200
    nuevo = _token_in(outbox[1])
    assert nuevo != viejo

    assert client.post("/auth/verify-email", json={"token": viejo}).status_code == 400
    assert client.post("/auth/verify-email", json={"token": nuevo}).status_code == 200


def test_reenviar_con_el_correo_ya_verificado_no_envia_nada(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    tokens = _register(client)
    client.post("/auth/verify-email", json={"token": _token_in(outbox[0])})

    r = client.post("/auth/resend-verification", headers=_auth(tokens))
    assert r.status_code == 200
    assert len(outbox) == 1


def test_reenviar_la_verificacion_tiene_limite(client: TestClient) -> None:
    tokens = _register(client)
    codigos = [
        client.post("/auth/resend-verification", headers=_auth(tokens)).status_code
        for _ in range(4)
    ]
    assert codigos == [200, 200, 200, 429]


def test_reenviar_exige_sesion(client: TestClient) -> None:
    assert client.post("/auth/resend-verification").status_code == 401


def test_sin_verificar_se_puede_iniciar_sesion(client: TestClient) -> None:
    """§5.2: la verificacion es requisito para pagar, no para entrar."""
    tokens = _register(client)
    r = client.post(
        "/auth/login", json={"email": tokens["user"]["email"], "password": PASSWORD}
    )
    assert r.status_code == 200
    assert r.json()["user"]["email_verified"] is False


# ---------- Olvide mi contrasena (§5.3) ----------


def test_forgot_password_responde_igual_exista_o_no_el_correo(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    """§5.8: misma respuesta, y ningun correo si la cuenta no existe."""
    tokens = _register(client)
    outbox.clear()

    existe = client.post("/auth/forgot-password", json={"email": tokens["user"]["email"]})
    no_existe = client.post("/auth/forgot-password", json={"email": _email()})

    assert existe.status_code == no_existe.status_code == 202
    assert existe.json() == no_existe.json()
    assert [m.to for m in outbox] == [tokens["user"]["email"]]


def test_forgot_password_tiene_limite_por_correo_exista_o_no(client: TestClient) -> None:
    """El limite corta igual para un correo sin cuenta: el 429 no revela nada."""
    for email in (_register(client)["user"]["email"], _email()):
        codigos = [
            client.post("/auth/forgot-password", json={"email": email}).status_code
            for _ in range(4)
        ]
        assert codigos == [202, 202, 202, 429]


def test_restablecer_la_contrasena(client: TestClient, outbox: list[EmailMessage]) -> None:
    email = _register(client)["user"]["email"]
    client.post("/auth/forgot-password", json={"email": email})
    token = _token_in(_last(outbox, "Restablece"))

    r = client.post("/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD})
    assert r.status_code == 200, r.text

    assert client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    ).status_code == 401
    assert client.post(
        "/auth/login", json={"email": email, "password": NEW_PASSWORD}
    ).status_code == 200
    assert _last(outbox, "cambió").to == email
    # El enlace no sirve dos veces.
    assert client.post(
        "/auth/reset-password", json={"token": token, "new_password": "una-tercera-clave-789"}
    ).status_code == 400


def test_tras_restablecer_el_refresh_token_anterior_da_401(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    """§5.8: restablecer cierra las sesiones abiertas."""
    tokens = _register(client)
    client.post("/auth/forgot-password", json={"email": tokens["user"]["email"]})
    token = _token_in(_last(outbox, "Restablece"))
    client.post("/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD})

    r = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401
    assert client.get("/auth/me", headers=_auth(tokens)).status_code == 401


def test_un_token_de_verificacion_no_sirve_para_restablecer(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    _register(client)
    r = client.post(
        "/auth/reset-password",
        json={"token": _token_in(outbox[0]), "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 400


def test_una_contrasena_rechazada_no_gasta_el_enlace(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    email = _register(client)["user"]["email"]
    client.post("/auth/forgot-password", json={"email": email})
    token = _token_in(_last(outbox, "Restablece"))

    # La politica que depende del usuario (igual a su correo) se revisa despues
    # de leer el token: si falla, el enlace tiene que seguir sirviendo.
    r = client.post("/auth/reset-password", json={"token": token, "new_password": email})
    assert r.status_code == 422
    assert client.post(
        "/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}
    ).status_code == 200


# ---------- Cambiar la contrasena con sesion (§5.3) ----------


def test_cambiar_la_contrasena_cierra_las_demas_sesiones(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    tokens = _register(client)
    email = tokens["user"]["email"]
    otra_sesion = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()

    r = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=_auth(tokens),
    )
    assert r.status_code == 200, r.text
    nuevos = r.json()

    # La sesion que hizo el cambio sigue, con los tokens nuevos.
    assert client.get("/auth/me", headers=_auth(nuevos)).status_code == 200
    assert client.post(
        "/auth/refresh", json={"refresh_token": nuevos["refresh_token"]}
    ).status_code == 200
    # Las demas, y los tokens viejos de esta, quedan fuera.
    assert client.get("/auth/me", headers=_auth(otra_sesion)).status_code == 401
    assert client.post(
        "/auth/refresh", json={"refresh_token": otra_sesion["refresh_token"]}
    ).status_code == 401
    assert client.get("/auth/me", headers=_auth(tokens)).status_code == 401
    assert _last(outbox, "cambió").to == email


def test_cambiar_la_contrasena_exige_la_actual(client: TestClient) -> None:
    tokens = _register(client)
    r = client.post(
        "/auth/change-password",
        json={"current_password": "no-es-esta-clave", "new_password": NEW_PASSWORD},
        headers=_auth(tokens),
    )
    # 400 y no 401: el cliente trata un 401 como sesion vencida.
    assert r.status_code == 400
    assert client.get("/auth/me", headers=_auth(tokens)).status_code == 200


# ---------- Politica de contrasenas (§5.3) ----------


@pytest.mark.parametrize(
    "password",
    ["corta-123", "password123", "1234567890", "aaaaaaaaaaaa", "abcdefghijkl", "Contraseña123"],
)
def test_el_registro_rechaza_contrasenas_debiles(client: TestClient, password: str) -> None:
    r = client.post("/auth/register", json={"email": _email(), "password": password})
    assert r.status_code == 422
    mensaje = r.json()["detail"][0]["msg"]
    assert "contraseña" in mensaje.lower()
    assert "Value error" not in mensaje


def test_la_contrasena_no_puede_ser_el_correo(client: TestClient) -> None:
    email = _email()
    r = client.post("/auth/register", json={"email": email, "password": email})
    assert r.status_code == 422
    assert "correo" in r.json()["detail"]


def test_una_cuenta_con_contrasena_corta_anterior_sigue_entrando(
    client: TestClient, db: Session
) -> None:
    """La politica aplica a contrasenas nuevas: no deja fuera a quien ya tenia cuenta."""
    from app.core.security import hash_password

    email = _register(client)["user"]["email"]
    db.execute(
        text("UPDATE users SET password_hash = :h WHERE email = :e"),
        {"h": hash_password("vieja123"), "e": email},
    )
    db.commit()

    r = client.post("/auth/login", json={"email": email, "password": "vieja123"})
    assert r.status_code == 200


# ---------- Sesiones anteriores al cambio (§5.3) ----------


def test_un_token_sin_version_sigue_valiendo_hasta_que_cambie_la_contrasena(
    client: TestClient,
) -> None:
    """Desplegar la revocacion no cierra la sesion de nadie."""
    import jwt

    from app.core.config import get_settings

    tokens = _register(client)
    settings = get_settings()
    claims = jwt.decode(
        tokens["access_token"], settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
    )
    assert claims["ver"] == 0
    del claims["ver"]
    viejo = jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    cabecera = {"Authorization": f"Bearer {viejo}"}
    assert client.get("/auth/me", headers=cabecera).status_code == 200

    client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=cabecera,
    )
    assert client.get("/auth/me", headers=cabecera).status_code == 401


# ---------- Perfil y cambio de correo (§5.4) ----------


def test_cambiar_el_nombre_visible(client: TestClient) -> None:
    tokens = _register(client)

    r = client.patch("/auth/me", json={"display_name": "  Carlos  "}, headers=_auth(tokens))
    assert r.status_code == 200
    assert r.json()["display_name"] == "Carlos"

    r = client.patch("/auth/me", json={"display_name": "   "}, headers=_auth(tokens))
    assert r.json()["display_name"] is None


def test_cambio_de_correo_se_aplica_solo_al_confirmar(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    tokens = _register(client)
    anterior = tokens["user"]["email"]
    nuevo = _email()
    outbox.clear()

    r = client.post(
        "/auth/change-email",
        json={"new_email": nuevo.upper(), "password": PASSWORD},
        headers=_auth(tokens),
    )
    assert r.status_code == 202, r.text

    # Confirmacion al correo nuevo, aviso al anterior.
    confirmacion = _last(outbox, "Confirma tu nuevo correo")
    aviso = _last(outbox, "Se pidió cambiar")
    assert confirmacion.to == nuevo
    assert aviso.to == anterior
    assert nuevo in aviso.text
    assert "token=" not in aviso.text, "el aviso al correo anterior no lleva el enlace"

    # Todavia no cambio nada.
    assert client.get("/auth/me", headers=_auth(tokens)).json()["email"] == anterior

    assert client.post(
        "/auth/verify-email", json={"token": _token_in(confirmacion)}
    ).status_code == 200
    me = client.get("/auth/me", headers=_auth(tokens)).json()
    assert me["email"] == nuevo
    assert me["email_verified"] is True
    assert client.post(
        "/auth/login", json={"email": nuevo, "password": PASSWORD}
    ).status_code == 200
    assert client.post(
        "/auth/login", json={"email": anterior, "password": PASSWORD}
    ).status_code == 401


def test_cambio_de_correo_exige_la_contrasena(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    tokens = _register(client)
    outbox.clear()
    r = client.post(
        "/auth/change-email",
        json={"new_email": _email(), "password": "no-es-esta-clave"},
        headers=_auth(tokens),
    )
    assert r.status_code == 400
    assert outbox == []


def test_cambio_de_correo_a_uno_ya_registrado_se_rechaza(client: TestClient) -> None:
    ocupado = _register(client)["user"]["email"]
    tokens = _register(client)
    r = client.post(
        "/auth/change-email",
        json={"new_email": ocupado, "password": PASSWORD},
        headers=_auth(tokens),
    )
    assert r.status_code == 409


def test_cambio_de_correo_falla_si_el_correo_se_ocupo_antes_de_confirmar(
    client: TestClient, outbox: list[EmailMessage]
) -> None:
    tokens = _register(client)
    disputado = _email()
    client.post(
        "/auth/change-email",
        json={"new_email": disputado, "password": PASSWORD},
        headers=_auth(tokens),
    )
    token = _token_in(_last(outbox, "Confirma tu nuevo correo"))
    _register(client, disputado)  # otra persona se registra con ese correo

    assert client.post("/auth/verify-email", json={"token": token}).status_code == 409
    assert client.get("/auth/me", headers=_auth(tokens)).json()["email"] != disputado


# ---------- El correo no rompe la peticion (§5.5) ----------


def test_un_smtp_caido_no_rompe_el_registro(client: TestClient) -> None:
    from app.core.email import get_email_sender
    from app.main import app

    class Roto:
        def send(self, message: EmailMessage) -> None:
            raise ConnectionError("SMTP caido")

    app.dependency_overrides[get_email_sender] = lambda: Roto()
    r = client.post("/auth/register", json={"email": _email(), "password": PASSWORD})
    assert r.status_code == 201
