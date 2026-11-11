"""Configuracion de la aplicacion, leida de variables de entorno."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
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

    # Pagos (docs/PLATAFORMA_COMPLETA.md §3, §3.18 y §3.19). `none` deja el
    # pago apagado: /planes muestra el precio y no deja suscribirse.
    # `tipsterpage` cobra con Tipster Page. `fake` es una pasarela simulada,
    # solo para desarrollo y tests de punta a punta.
    payment_provider: Literal["none", "fake", "tipsterpage"] = "none"
    # Donde responde esta API, vista desde fuera: el enlace de un solo uso de
    # la pagina de pago y la URL a la que la pasarela manda sus avisos.
    api_public_url: str = "http://localhost:8000"
    # Tipster Page (payments/tipsterpage.py). Las cuatro, o ninguna. La URL
    # base dice el ambiente: la del sandbox o la de produccion.
    tspay_api_base_url: str = ""
    tspay_merchant_code: str = ""
    tspay_auth_bearer: str = ""
    tspay_secret_key: str = ""

    # Tasas de la factura (core/exchange_rates.py). El token de la app en
    # datos.gov.co es opcional: sin el, la consulta de la TRM va por el limite
    # compartido por IP. No es un secreto de cobro, pero no va en un log.
    datos_gov_app_token: str = ""

    # Emision de la factura electronica (invoicing/; §3.17, "Paso 5.4").
    # `none` la deja apagada: las facturas se quedan `pending`. `fake` es un
    # emisor simulado, solo para desarrollo y Playwright. `siigo` emite con la
    # API de Siigo y pide las siete SIIGO_* de abajo menos la URL base.
    invoice_issuer: Literal["none", "fake", "siigo"] = "none"
    siigo_api_base_url: str = "https://api.siigo.com"
    siigo_username: str = ""
    siigo_access_key: str = ""
    # El nombre de la aplicacion registrado en Siigo: va en la cabecera
    # Partner-Id de cada peticion.
    siigo_partner_id: str = ""
    # Los ids de la cuenta en Siigo Nube (scripts/siigo_catalogs.py los lista):
    # el tipo de comprobante de factura electronica, el vendedor, la forma de
    # pago y el codigo del producto "suscripcion".
    siigo_document_type_id: int = 0
    siigo_seller_id: int = 0
    siigo_payment_type_id: int = 0
    siigo_product_code: str = ""
    # El centro de costo, si el tipo de comprobante lo pide (su `cost_center`
    # en /v1/document-types). 0 = no se manda.
    siigo_cost_center_id: int = 0
    # El impuesto de IVA del 0 % de la operacion excluida (su id en /v1/taxes),
    # para que la factura lo muestre. 0 = el item va sin impuestos.
    siigo_tax_id: int = 0
    # El tipo de comprobante de nota credito electronica (su id en
    # /v1/document-types?type=NC). 0 = las notas credito esperan (pendientes)
    # hasta que se configure; las facturas salen igual.
    siigo_credit_note_document_type_id: int = 0
    # Cuantas horas espera la factura despues de aprobado el pago antes de
    # emitirse (la contadora, 2026-11-11: que no se facture hasta que el pago
    # este aceptado; un reembolso o una anulacion en ese plazo cancela la
    # factura sin nota credito). 0 = enseguida, como hasta ahora.
    invoice_hold_hours: int = Field(default=0, ge=0, le=24 * 30)
    # Espera minima entre peticiones a Siigo. La empresa de pruebas no admite
    # rafagas (10 por minuto): alli conviene 8. En produccion, 100 por minuto.
    siigo_min_interval_seconds: float = 1.0

    # Verificacion contra bots con Cloudflare Turnstile (core/bot_check.py). Van
    # las dos o ninguna; sin ninguna, la verificacion queda apagada.
    turnstile_site_key: str = ""
    turnstile_secret_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
