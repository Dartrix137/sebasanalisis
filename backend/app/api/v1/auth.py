"""Router de autenticacion: registro, login, refresh y perfil.

El registro deja la cuenta activa de inmediato con `access_type='trial'` — no hay
verificacion de correo en el MVP (§4). La columna `users.email_verified` existe
preparada, siempre en False, sin logica asociada todavia.
"""

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core import rate_limit
from app.core.security import (
    TokenError,
    create_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.models import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Mensaje unico para credenciales malas: no revela si el correo existe (§3.6).
_INVALID_CREDENTIALS = "Correo o contrasena incorrectos"


def _tokens_for(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_token(user.id, "access"),
        refresh_token=create_token(user.id, "refresh"),
        user=UserResponse.model_validate(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: DbSession) -> TokenResponse:
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Ya existe una cuenta con ese correo"
        )
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        access_type="trial",
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _tokens_for(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession, request: Request) -> TokenResponse:
    email = payload.email.lower()
    client_ip = request.client.host if request.client else "unknown"
    key = f"{client_ip}:{email}"

    if rate_limit.is_rate_limited(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Espera unos minutos antes de reintentar",
        )

    user = db.scalar(select(User).where(User.email == email))
    # Se verifica el hash aunque el usuario no exista para no filtrar por tiempo
    # de respuesta si un correo esta registrado o no.
    valid = verify_password(payload.password, user.password_hash) if user else False
    if not user or not valid:
        rate_limit.register_failure(key)
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
    try:
        user_id = decode_token(payload.refresh_token, "refresh")
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesion expirada, inicia sesion de nuevo"
        ) from None
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesion expirada, inicia sesion de nuevo"
        )
    return _tokens_for(user)


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser) -> User:
    return user
