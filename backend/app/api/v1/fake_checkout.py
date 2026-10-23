"""Pagina de la pasarela simulada. Solo responde con `PAYMENT_PROVIDER=fake`.

Hace de "pagina de la pasarela" en desarrollo y en los tests de punta a punta:
dos botones, aprobar y rechazar. Anota el resultado en `FakePaymentProvider` y
devuelve al cliente a la aplicacion con `?id=`, como haria una pasarela. La aplicacion
se entera igual que en produccion: reconsultando.

Con cualquier otro proveedor estas rutas responden 404, y no aparecen en el
OpenAPI.
"""

from html import escape
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse

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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="redirect_url inválida")


@router.get("/{documento}", response_class=HTMLResponse)
def fake_contract(_: FakeProvider, documento: Literal["terminos", "datos"]) -> str:
    """Hace de contrato del procesador de pagos en la pasarela simulada."""
    titulo = "Términos de uso" if documento == "terminos" else "Tratamiento de datos personales"
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        f"<title>{titulo}</title></head><body><h1>{titulo}</h1>"
        "<p>Documento de la pasarela simulada. Solo desarrollo y pruebas.</p></body></html>"
    )


@router.get("", response_class=HTMLResponse)
def fake_checkout_page(
    _: FakeProvider,
    reference: Annotated[str, Query(max_length=255)],
    amount_cents: Annotated[int, Query(gt=0)],
    currency: Annotated[str, Query(max_length=3)],
    redirect_url: Annotated[str, Query(max_length=2000)],
) -> str:
    _check_redirect(redirect_url)
    hidden = "".join(
        f'<input type="hidden" name="{name}" value="{escape(str(value), quote=True)}">'
        for name, value in (
            ("reference", reference),
            ("amount_cents", amount_cents),
            ("currency", currency),
            ("redirect_url", redirect_url),
        )
    )
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Pasarela simulada</title></head>
<body style="font-family:sans-serif;max-width:32rem;margin:3rem auto;padding:0 1rem;">
<h1>Pasarela simulada</h1>
<p><strong>Solo desarrollo y pruebas. Aquí no se cobra nada.</strong></p>
<p>Referencia: {escape(reference)}<br>Monto: {amount_cents} centavos {escape(currency)}</p>
<form method="post">{hidden}
<button name="outcome" value="approved">Aprobar el pago</button>
<button name="outcome" value="declined">Rechazar el pago</button>
</form>
</body></html>"""


@router.post("")
def fake_checkout_resolve(
    provider: FakeProvider,
    reference: Annotated[str, Form(max_length=255)],
    amount_cents: Annotated[int, Form(gt=0)],
    currency: Annotated[str, Form(max_length=3)],
    redirect_url: Annotated[str, Form(max_length=2000)],
    outcome: Annotated[Literal["approved", "declined"], Form()],
) -> RedirectResponse:
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
