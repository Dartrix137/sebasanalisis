"""Router de autenticacion y cuenta (docs/PLATAFORMA_COMPLETA.md §5).

Registro, login y refresh; verificacion del correo; olvido, restablecimiento y
cambio de contrasena con revocacion de sesiones; nombre visible y cambio de
correo; consentimientos del registro y exportacion de datos (§6.3 y §6.4).

Tres reglas que atraviesan el archivo:

- Los correos se envian en `BackgroundTasks`, despues de responder: un SMTP lento
  no demora la peticion y uno caido no la rompe.
- Los tokens de un solo uso se emiten y se consumen en la misma transaccion que
  el cambio que acompanan.
- Ninguna respuesta revela si un correo esta registrado, salvo el registro y el
  cambio de correo, que no pueden evitar decir "ese correo ya tiene cuenta".
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select

from app.api.deps import CurrentUser, DbSession
from app.api.v1.legal import client_ip, list_consents
from app.core import legal, rate_limit
from app.core.config import get_settings
from app.core.email import EmailSender, get_email_sender, send_safely
from app.core.password_policy import PasswordPolicyError, validate_password
from app.core.security import (
    TokenError,
    create_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.core.user_tokens import TOKEN_TTL, InvalidTokenError, consume_token, issue_token
from app.emails import build_email
from app.models import Bet, GameSession, Spin, User
from app.schemas.auth import (
    ChangeEmailRequest,
    ChangePasswordRequest,
    DeleteAccountRequest,
    ExportResponse,
    ExportSession,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserResponse,
)
from app.schemas.bets import BetResponse
from app.schemas.sessions import SessionResponse
from app.schemas.spins import SpinResponse

router = APIRouter(prefix="/auth", tags=["auth"])

EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]

# Mensaje unico para credenciales malas: no revela si el correo existe (§3.6).
_INVALID_CREDENTIALS = "Correo o contrasena incorrectos"
_SESSION_EXPIRED = "Sesion expirada, inicia sesion de nuevo"
_INVALID_LINK = "El enlace no es válido o ya venció. Pide uno nuevo"
_WRONG_PASSWORD = "La contraseña actual no es correcta"
_TOO_MANY = "Demasiados intentos. Espera unos minutos antes de reintentar"
# La misma respuesta exista o no el correo (§5.3).
_FORGOT_SENT = (
    "Si ese correo tiene una cuenta, te enviamos un enlace para restablecer la contraseña"
)

_ADULT_REQUIRED = "Para crear una cuenta debes declarar que eres mayor de edad"
_CONSENTS_REQUIRED = (
    "Para crear una cuenta debes aceptar los Términos y Condiciones y la "
    "Política de Tratamiento de Datos Personales vigentes"
)

_MINUTE = 60
_HOUR = 3600
_DAY = 24 * _HOUR

# Fallos de login desde una misma IP, sin importar contra que correo.
_LOGIN_IP_MAX_FAILURES = 30
_LOGIN_IP_WINDOW = 15 * _MINUTE


def _now() -> datetime:
    return datetime.now(UTC)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _limit(key: str, *, limit: int, window: int) -> None:
    """Corta con 429 si la clave supero su limite (§5.6)."""
    if not get_settings().rate_limit_enabled:
        return
    if not rate_limit.hit(key, limit=limit, window=window):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=_TOO_MANY)


def _tokens_for(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_token(user.id, "access", token_version=user.token_version),
        refresh_token=create_token(user.id, "refresh", token_version=user.token_version),
        user=UserResponse.model_validate(user),
    )


def _frontend_url(path: str) -> str:
    return f"{get_settings().frontend_base_url.rstrip('/')}{path}"


def _check_new_password(password: str, email: str) -> None:
    """La parte de la politica que necesita conocer al usuario."""
    try:
        validate_password(password, email=email)
    except PasswordPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


def _queue_verification_email(
    db: DbSession, user: User, background: BackgroundTasks, sender: EmailSender
) -> None:
    """Emite el token de verificacion y deja el correo en cola. No hace commit."""
    raw_token = issue_token(db, user, "verify_email", now=_now())
    message = build_email(
        "verify_email",
        to=user.email,
        display_name=user.display_name,
        url=_frontend_url(f"/verificar-correo?token={raw_token}"),
        hours=int(TOKEN_TTL["verify_email"].total_seconds() // _HOUR),
    )
    background.add_task(send_safely, sender, message)


def _queue_password_changed_email(
    user: User, background: BackgroundTasks, sender: EmailSender
) -> None:
    message = build_email(
        "password_changed",
        to=user.email,
        display_name=user.display_name,
        forgot_url=_frontend_url("/olvide-contrasena"),
    )
    background.add_task(send_safely, sender, message)


# ---------- Registro, login, refresh ----------


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    db: DbSession,
    request: Request,
    background: BackgroundTasks,
    sender: EmailSenderDep,
) -> TokenResponse:
    # Cada registro envia un correo a la direccion que se escriba, sea de quien
    # sea: sin tope, la plataforma serviria para mandar correo a terceros.
    _limit(f"register:{_client_ip(request)}", limit=10, window=_HOUR)
    _limit(f"register-day:{_client_ip(request)}", limit=20, window=_DAY)

    email = payload.email.lower()
    _check_new_password(payload.password, email)

    # Sin consentimientos no hay cuenta (§6.3). Se revisa antes de mirar si el
    # correo existe: un registro incompleto no revela nada sobre otras cuentas.
    if not payload.adult_confirmed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_ADULT_REQUIRED
        )
    required = legal.required_documents(db)
    accepted = set(payload.accepted_document_ids)
    if any(doc.id not in accepted for doc in required):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_CONSENTS_REQUIRED
        )

    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Ya existe una cuenta con ese correo"
        )
    now = _now()
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        access_type="trial",
        role="user",
        adult_confirmed_at=now,
    )
    db.add(user)
    db.flush()
    # Solo los exigidos: un id de mas en la peticion no crea una aceptacion de
    # un documento que el formulario no pide. Todos son la version vigente
    # (salen de `required_documents`), asi que aqui no hay version vencida.
    legal.record_consents(
        db,
        user,
        [doc.id for doc in required],
        now=now,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    _queue_verification_email(db, user, background, sender)
    db.commit()
    db.refresh(user)
    return _tokens_for(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession, request: Request) -> TokenResponse:
    email = payload.email.lower()
    ip = _client_ip(request)
    key = f"{ip}:{email}"
    # Dos limites de fallos. Por IP y correo: frena insistir contra una cuenta.
    # Por IP sola: frena probar pocas contrasenas contra muchos correos, que el
    # primero no ve porque cada correo estrena su propia cuenta.
    ip_key = f"login-ip:{ip}"

    if (
        rate_limit.is_rate_limited(key)
        or rate_limit.failures(ip_key, _LOGIN_IP_WINDOW) >= _LOGIN_IP_MAX_FAILURES
    ):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=_TOO_MANY)

    user = db.scalar(select(User).where(User.email == email))
    # Se verifica el hash aunque el usuario no exista para no filtrar por tiempo
    # de respuesta si un correo esta registrado o no.
    valid = verify_password(payload.password, user.password_hash) if user else False
    if not user or not valid:
        rate_limit.register_failure(key)
        rate_limit.register_failure(ip_key, _LOGIN_IP_WINDOW)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS
        )

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
        db.commit()

    rate_limit.reset(key)
    return _tokens_for(user)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: DbSession) -> TokenResponse:
    expired = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_SESSION_EXPIRED)
    try:
        claims = decode_token(payload.refresh_token, "refresh")
    except TokenError:
        raise expired from None
    user = db.get(User, claims.user_id)
    # Version distinta: la contrasena cambio y esa sesion quedo revocada (§5.3).
    if user is None or claims.token_version != user.token_version:
        raise expired
    return _tokens_for(user)


# ---------- Perfil ----------


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser) -> User:
    return user


@router.patch("/me", response_model=UserResponse)
def update_profile(payload: UpdateProfileRequest, user: CurrentUser, db: DbSession) -> User:
    nombre = (payload.display_name or "").strip()
    user.display_name = nombre or None
    db.commit()
    db.refresh(user)
    return user


@router.post("/me/onboarding", response_model=UserResponse)
def complete_onboarding(user: CurrentUser, db: DbSession) -> User:
    """Anota que la cuenta leyo la pantalla de bienvenida de la mesa (§6.3).

    Es informativa, no un consentimiento legal: por eso vive aqui y no en
    `user_consents`, y por eso no decide el acceso.
    """
    if user.onboarding_completed_at is None:
        user.onboarding_completed_at = _now()
        db.commit()
        db.refresh(user)
    return user


@router.get("/me/export", response_model=ExportResponse)
def export_my_data(user: CurrentUser, db: DbSession) -> ExportResponse:
    """Todos los datos de la cuenta en un JSON (derecho de consulta, §6.4).

    No exige `RequireAccess`: consultar los datos propios no depende de tener
    acceso a la mesa ni de haber aceptado la version vigente de un documento.
    """
    _limit(f"export:{user.id}", limit=10, window=15 * _MINUTE)

    sessions = list(
        db.scalars(
            select(GameSession)
            .where(GameSession.user_id == user.id)
            .order_by(GameSession.started_at)
        )
    )
    ids = [s.id for s in sessions]
    spins: dict[object, list[SpinResponse]] = {i: [] for i in ids}
    bets: dict[object, list[BetResponse]] = {i: [] for i in ids}
    if ids:
        for spin in db.scalars(
            select(Spin).where(Spin.session_id.in_(ids)).order_by(Spin.spin_index)
        ):
            spins[spin.session_id].append(SpinResponse.model_validate(spin))
        for bet in db.scalars(
            select(Bet).where(Bet.session_id.in_(ids)).order_by(Bet.created_at)
        ):
            bets[bet.session_id].append(BetResponse.model_validate(bet))

    return ExportResponse(
        exported_at=_now(),
        account=UserResponse.model_validate(user),
        sessions=[
            ExportSession(
                session=SessionResponse.model_validate(s), spins=spins[s.id], bets=bets[s.id]
            )
            for s in sessions
        ],
        consents=list_consents(db, user.id),
        # Los cobros llegan en el paso 5 (Wompi). Hasta entonces no hay ninguno.
        payments=[],
    )


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    payload: DeleteAccountRequest,
    user: CurrentUser,
    db: DbSession,
    background: BackgroundTasks,
    sender: EmailSenderDep,
) -> None:
    """Elimina la cuenta y todos sus datos (derecho de supresion, §5.4 y §6.4).

    Borra el usuario; la base arrastra en cascada sus mesas, numeros, apuestas,
    recomendaciones y tokens. No queda nada que lo identifique.

    Pendiente del paso 5: cuando haya pagos, primero se cancela la renovacion y
    los registros de pago se conservan anonimizados por obligacion contable.
    """
    _limit(f"delete-account:{user.id}", limit=10, window=15 * _MINUTE)

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_WRONG_PASSWORD)

    # Sin administrador nadie puede gestionar juegos ni usuarios, y no hay forma
    # de crear otro desde la aplicacion.
    if user.role == "admin":
        otros = db.scalar(
            select(func.count()).select_from(User).where(User.role == "admin", User.id != user.id)
        )
        if not otros:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Eres el único administrador: nombra otro antes de eliminar tu cuenta",
            )

    # El correo se arma antes de borrar: despues ya no hay a quien escribirle.
    message = build_email("account_deleted", to=user.email, display_name=user.display_name)
    # DELETE directo y no db.delete(user): el borrado en cascada lo hace la base
    # (ON DELETE CASCADE), no el ORM cargando y anulando fila por fila.
    db.execute(delete(User).where(User.id == user.id))
    db.commit()
    background.add_task(send_safely, sender, message)


# ---------- Verificacion del correo ----------


@router.post("/verify-email", response_model=MessageResponse)
def verify_email(payload: TokenRequest, db: DbSession, request: Request) -> MessageResponse:
    """Confirma un correo: el de la cuenta nueva, o el nuevo de un cambio de correo."""
    _limit(f"verify-email:{_client_ip(request)}", limit=20, window=15 * _MINUTE)

    now = _now()
    try:
        token = consume_token(db, payload.token, ("verify_email", "change_email"), now=now)
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_LINK
        ) from None

    user = db.get(User, token.user_id)
    if user is None:  # la cuenta se elimino con el enlace todavia en el correo
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_LINK)

    if token.purpose == "change_email":
        new_email = token.new_email or ""
        # Se vuelve a mirar al confirmar: entre pedir el cambio y abrir el
        # enlace, otra cuenta pudo registrarse con ese correo.
        if db.scalar(select(User).where(User.email == new_email, User.id != user.id)):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe una cuenta con ese correo",
            )
        user.email = new_email

    user.email_verified = True
    user.email_verified_at = now
    db.commit()
    return MessageResponse(message="Tu correo quedó confirmado")


@router.post("/resend-verification", response_model=MessageResponse)
def resend_verification(
    user: CurrentUser, db: DbSession, background: BackgroundTasks, sender: EmailSenderDep
) -> MessageResponse:
    if user.email_verified:
        return MessageResponse(message="Tu correo ya está confirmado")
    # De la ventana mas corta a la mas larga: un intento rechazado por la espera
    # de un minuto no gasta los cupos de 15 minutos ni del dia. El tope diario
    # existe porque 3 cada 15 minutos son 288 correos al dia desde una sola
    # cuenta, mas que la cuota diaria del proveedor.
    _limit(f"resend-verification:min:{user.id}", limit=1, window=_MINUTE)
    _limit(f"resend-verification:{user.id}", limit=3, window=15 * _MINUTE)
    _limit(f"resend-verification:day:{user.id}", limit=10, window=_DAY)

    _queue_verification_email(db, user, background, sender)
    db.commit()
    return MessageResponse(message="Te enviamos un nuevo correo de confirmación")


# ---------- Contrasena ----------


@router.post(
    "/forgot-password", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED
)
def forgot_password(
    payload: ForgotPasswordRequest,
    db: DbSession,
    request: Request,
    background: BackgroundTasks,
    sender: EmailSenderDep,
) -> MessageResponse:
    """Responde siempre igual, exista o no el correo (§5.3).

    Los limites se aplican antes de mirar la base, asi que un 429 tampoco dice
    nada sobre si la cuenta existe.
    """
    email = payload.email.lower()
    _limit(f"forgot-password:ip:{_client_ip(request)}", limit=10, window=15 * _MINUTE)
    _limit(f"forgot-password:email:{email}", limit=3, window=15 * _MINUTE)
    # Sin tope por dia, 3 cada 15 minutos son 288 correos diarios a un mismo buzon.
    _limit(f"forgot-password:email-day:{email}", limit=10, window=_DAY)

    user = db.scalar(select(User).where(User.email == email))
    if user is not None:
        raw_token = issue_token(db, user, "reset_password", now=_now())
        db.commit()
        message = build_email(
            "reset_password",
            to=user.email,
            display_name=user.display_name,
            url=_frontend_url(f"/restablecer-contrasena?token={raw_token}"),
            minutes=int(TOKEN_TTL["reset_password"].total_seconds() // _MINUTE),
        )
        background.add_task(send_safely, sender, message)
    return MessageResponse(message=_FORGOT_SENT)


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(
    payload: ResetPasswordRequest,
    db: DbSession,
    request: Request,
    background: BackgroundTasks,
    sender: EmailSenderDep,
) -> MessageResponse:
    _limit(f"reset-password:{_client_ip(request)}", limit=10, window=15 * _MINUTE)

    try:
        token = consume_token(db, payload.token, ("reset_password",), now=_now())
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_LINK
        ) from None
    user = db.get(User, token.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_LINK)

    # Si la politica la rechaza, la excepcion deshace la transaccion y el token
    # sigue sin usar: el usuario corrige la contrasena con el mismo enlace.
    _check_new_password(payload.new_password, user.email)
    user.password_hash = hash_password(payload.new_password)
    # Cierra todas las sesiones abiertas: quien pide restablecer puede haber
    # perdido el control de la cuenta.
    user.token_version += 1
    db.commit()

    _queue_password_changed_email(user, background, sender)
    return MessageResponse(message="Tu contraseña cambió. Inicia sesión con la nueva")


@router.post("/change-password", response_model=TokenResponse)
def change_password(
    payload: ChangePasswordRequest,
    user: CurrentUser,
    db: DbSession,
    background: BackgroundTasks,
    sender: EmailSenderDep,
) -> TokenResponse:
    """Cambia la contrasena y cierra las demas sesiones.

    Devuelve tokens nuevos para que esta sesion siga abierta: los anteriores
    dejaron de valer junto con los de cualquier otro dispositivo.
    """
    _limit(f"change-password:{user.id}", limit=10, window=15 * _MINUTE)

    # 400 y no 401: el cliente trata un 401 como sesion vencida e intentaria
    # renovarla, cuando lo que pasa es que la contrasena escrita esta mal.
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_WRONG_PASSWORD)
    _check_new_password(payload.new_password, user.email)

    user.password_hash = hash_password(payload.new_password)
    user.token_version += 1
    db.commit()
    db.refresh(user)

    _queue_password_changed_email(user, background, sender)
    return _tokens_for(user)


# ---------- Cambio de correo ----------


@router.post(
    "/change-email", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED
)
def change_email(
    payload: ChangeEmailRequest,
    user: CurrentUser,
    db: DbSession,
    background: BackgroundTasks,
    sender: EmailSenderDep,
) -> MessageResponse:
    """Pide cambiar el correo. Se aplica al confirmar el enlace que llega al nuevo."""
    _limit(f"change-email:{user.id}", limit=5, window=_HOUR)
    # Cada solicitud envia dos correos (confirmacion y aviso): sin tope por dia,
    # 5 por hora son 240 correos diarios desde una sola cuenta.
    _limit(f"change-email:day:{user.id}", limit=10, window=_DAY)

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_WRONG_PASSWORD)

    new_email = payload.new_email.lower()
    if new_email == user.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Ese ya es el correo de tu cuenta"
        )
    if db.scalar(select(User).where(User.email == new_email)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Ya existe una cuenta con ese correo"
        )

    raw_token = issue_token(db, user, "change_email", now=_now(), new_email=new_email)
    db.commit()

    confirm = build_email(
        "change_email_confirm",
        to=new_email,
        display_name=user.display_name,
        url=_frontend_url(f"/verificar-correo?token={raw_token}"),
        hours=int(TOKEN_TTL["change_email"].total_seconds() // _HOUR),
    )
    notice = build_email(
        "change_email_notice",
        to=user.email,
        display_name=user.display_name,
        new_email=new_email,
        forgot_url=_frontend_url("/olvide-contrasena"),
    )
    background.add_task(send_safely, sender, confirm)
    background.add_task(send_safely, sender, notice)
    return MessageResponse(
        message=f"Te enviamos un enlace a {new_email}. El cambio se aplica cuando lo confirmes"
    )
