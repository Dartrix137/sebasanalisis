"""La interfaz con el emisor de facturas electronicas (docs/PLATAFORMA_COMPLETA.md
§3.17, "Paso 5.4", punto 1; Fase 5, paso 5.4).

La aplicacion nunca habla con Siigo directamente: habla con `InvoiceIssuer`.
`INVOICE_ISSUER` elige la implementacion: `none` (por defecto: la emision queda
apagada y las facturas se quedan `pending`), `fake` (simulado: solo desarrollo
y Playwright) o `siigo` (`invoicing/siigo.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Protocol

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class Buyer:
    """El comprador, con los codigos de Siigo. Datos personales: no van a un log."""

    id_type: str
    id_number: str
    first_names: str
    last_names: str
    email: str
    address: str
    country_code: str
    state_code: str
    city_code: str


@dataclass(frozen=True)
class InvoiceDraft:
    """Lo que se manda a facturar, ya congelado."""

    idempotency_key: str
    issue_date: date
    buyer: Buyer
    description: str
    amount: Decimal  # en pesos, con 2 decimales
    observations: str


@dataclass(frozen=True)
class IssuedInvoice:
    """Una factura en el emisor, como la devolvio."""

    provider_id: str
    name: str | None
    total: Decimal | None
    #: `Draft`, `Accepted` o `Rejected` en Siigo; None si no lo dijo.
    stamp_status: str | None
    cufe: str | None = None
    mail_status: str | None = None


class IssuerError(Exception):
    """Algo fallo al hablar con el emisor."""

    def __init__(self, message: str, codes: list[str] | None = None) -> None:
        super().__init__(message)
        self.codes = codes or []


class IssuerTransient(IssuerError):
    """Pasajero (limite, caida, tiempo agotado): se reintenta en otra corrida.

    `uncertain` dice que la peticion pudo haber llegado (tiempo agotado): el
    reintento manda la misma `Idempotency-Key`.
    """

    def __init__(
        self,
        message: str,
        codes: list[str] | None = None,
        *,
        retry_after: float | None = None,
        uncertain: bool = False,
    ) -> None:
        super().__init__(message, codes)
        self.retry_after = retry_after
        self.uncertain = uncertain


class IssuerMisconfigured(IssuerError):
    """De la configuracion de la cuenta: frena toda la corrida."""


class IssuerRejected(IssuerError):
    """El emisor rechazo los datos de esta factura: no se reintenta sola."""


@dataclass
class StampErrors:
    messages: list[str] = field(default_factory=list)


class InvoiceIssuer(Protocol):
    name: str

    @property
    def enabled(self) -> bool: ...

    def describe(self) -> str: ...

    def check_ready(self) -> None:
        """Comprueba la configuracion contra el emisor antes de emitir.
        `IssuerMisconfigured` si no sirve, `IssuerTransient` si no respondio."""
        ...

    def issue(self, draft: InvoiceDraft) -> IssuedInvoice: ...

    def fetch(self, provider_id: str) -> IssuedInvoice: ...

    def stamp_errors(self, provider_id: str) -> list[str]: ...


class DisabledIssuer:
    """`INVOICE_ISSUER=none`: la emision esta apagada."""

    name = "none"
    enabled = False

    def describe(self) -> str:
        return "apagada"

    def check_ready(self) -> None:
        raise IssuerMisconfigured("La emision de facturas esta apagada")

    def issue(self, draft: InvoiceDraft) -> IssuedInvoice:
        raise IssuerMisconfigured("La emision de facturas esta apagada")

    def fetch(self, provider_id: str) -> IssuedInvoice:
        raise IssuerMisconfigured("La emision de facturas esta apagada")

    def stamp_errors(self, provider_id: str) -> list[str]:
        raise IssuerMisconfigured("La emision de facturas esta apagada")


class IssuerConfigError(RuntimeError):
    """La configuracion no deja arrancar (como `ProviderMisconfigured`)."""


def build_invoice_issuer(settings: Settings) -> InvoiceIssuer:
    from app.invoicing import siigo
    from app.invoicing.fake import FakeInvoiceIssuer
    from app.payments.tipsterpage import has_production_keys

    if settings.invoice_issuer == "fake":
        # El simulado da por aceptadas facturas que no existen: con las llaves
        # de produccion de la pasarela dejaria pagos reales sin factura.
        if has_production_keys(settings):
            raise IssuerConfigError(
                "INVOICE_ISSUER=fake no se usa con llaves de produccion de Tipster Page"
            )
        return FakeInvoiceIssuer()
    if settings.invoice_issuer == "siigo":
        return siigo.from_settings(settings)
    return DisabledIssuer()


@lru_cache
def get_invoice_issuer() -> InvoiceIssuer:
    """Dependencia de FastAPI y del job. Los tests la sustituyen."""
    return build_invoice_issuer(get_settings())
