"""Pasarela simulada: el boton de su pagina. Solo responde con `PAYMENT_PROVIDER=fake`.

La pagina misma la arma `FakePaymentProvider.start_checkout` y la sirve el
enlace de un solo uso (`GET /billing/checkout/{token}`), como la de una
pasarela real. Sus dos botones llegan aqui: se anota el resultado en
`FakePaymentProvider` y se devuelve al cliente a la aplicacion con `?id=`. La
aplicacion se entera igual que en produccion: reconsultando.

Con cualquier otro proveedor esta ruta responde 404, y no aparece en el OpenAPI.
"""

from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.payments.base import PaymentProvider, get_payment_provider
from app.payments.fake import FakePaymentProvider

router = APIRouter(prefix="/dev/fake-checkout", include_in_schema=False)


def _fake(provider: Annotated[PaymentProvider, Depends(get_payment_provider)]) -> FakePaymentProvider:
    if not isinstance(provider, FakePaymentProvider):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return provider


FakeProvider = Annotated[FakePaymentProvider, Depends(_fake)]


def _check_redirect(redirect_url: str) -> None:
    """Solo se devuelve al frontend de esta instalacion."""
    base = get_settings().frontend_base_url.rstrip("/")
    if not redirect_url.startswith(f"{base}/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="URL de regreso inválida")


@router.post("")
def fake_checkout_resolve(
    provider: FakeProvider,
    reference: Annotated[str, Form(max_length=255)],
    amount_cents: Annotated[int, Form(gt=0)],
    currency: Annotated[str, Form(max_length=3)],
    url_ok: Annotated[str, Form(max_length=2000)],
    url_ko: Annotated[str, Form(max_length=2000)],
    outcome: Annotated[Literal["approved", "declined"], Form()],
) -> RedirectResponse:
    redirect_url = url_ok if outcome == "approved" else url_ko
    _check_redirect(redirect_url)
    transaction = provider.resolve(
        reference=reference,
        amount_cents=amount_cents,
        currency=currency,
        status=outcome,
        status_message=None if outcome == "approved" else "Rechazado en la pasarela simulada",
    )
    separator = "&" if "?" in redirect_url else "?"
    return RedirectResponse(
        f"{redirect_url}{separator}{urlencode({'id': transaction.id})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
