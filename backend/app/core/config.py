"""Configuracion de la aplicacion, leida de variables de entorno."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Sebasanalisis API"
    # Origenes del frontend autorizados a llamar la API. En produccion se
    # restringe al dominio real; nunca "*", porque la API usa Authorization.
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    database_url: str = "postgresql+psycopg://sebas:sebas@localhost:5434/sebasanalisis"

    jwt_secret_key: str = "cambia-esto-en-produccion"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30

    seed_admin_email: str = "admin@sebasanalisis.com"
    seed_admin_password: str = "cambia-esta-clave"

    # DSN del proyecto de la API en GlitchTip. Vacio = monitoreo desactivado.
    sentry_dsn: str = ""

    # Solo se apaga en los tests de punta a punta, donde todas las peticiones
    # salen de la misma IP y el limite por IP las cortaria. Nunca en produccion.
    rate_limit_enabled: bool = True

    # Base de los enlaces que viajan en los correos (verificar, restablecer).
    frontend_base_url: str = "http://localhost:3000"

    # Correo (docs/PLATAFORMA_COMPLETA.md §5.5). `console` imprime el correo en
    # el log y es el valor por defecto: sin configurar nada, no se envia nada.
    email_backend: Literal["smtp", "console", "file"] = "console"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "Sebasanálisis <no-responder@localhost>"
    smtp_use_tls: bool = True
    # Tope de correos por dia (UTC) que la API acepta enviar; al llegar, corta y
    # lo registra como error. Debe quedar por debajo del limite diario del plan
    # del proveedor. 0 lo desactiva.
    email_daily_limit: int = 300
    # Solo con EMAIL_BACKEND=file (tests de punta a punta).
    email_file_dir: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
