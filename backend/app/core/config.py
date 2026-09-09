"""Configuracion de la aplicacion, leida de variables de entorno."""

from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
