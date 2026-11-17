"""Pasarela simulada: el boton de su pagina. Solo responde con `PAYMENT_PROVIDER=fake`.

La pagina misma la arma `FakePaymentProvider.start_checkout` y la sirve el
enlace de un solo uso (`GET /billing/checkout/{token}`), como la de una
pasarela real. Sus dos botones llegan aqui: se anota el resultado en
`FakePaymentProvider` y se devuelve al cliente a la aplicacion con `?id=`. La
aplicacion se entera igual que en produccion: reconsultando.

El alta de la renovacion automatica tiene su propia pagina, que sirve esta ruta
(`/subscription/:token`), como la de Solidgate en Tipster Page (paso 5.3b).

Con cualquier otro proveedor esta ruta responde 404, y no aparece en el OpenAPI.
"""

from html import escape
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Path, status
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


# ---------- Alta de la renovacion automatica (como Solidgate en Tipster Page) ----------

_RECURRING_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Pasarela simulada</title></head>
<body style="font-family:sans-serif;max-width:32rem;margin:3rem auto;padding:0 1rem;">
<h1>Pasarela simulada: renovación automática</h1>
<p><strong>Solo desarrollo y pruebas. Aquí no se cobra nada.</strong></p>
<p>Referencia: {reference}<br>{what}: {amount} {currency}</p>
<form method="post" action="{action}">
<button name="outcome" value="approved">Pagar y guardar la tarjeta</button>
<button name="outcome" value="approved_declining">Pagar con una tarjeta que rechaza las renovaciones</button>
<button name="outcome" value="declined">Rechazar el pago</button>
</form>
</body></html>"""


def _page_csp() -> str:
    frontend = get_settings().frontend_base_url.rstrip("/")
    return (
        "default-src 'none'; style-src 'unsafe-inline'; "
        f"form-action 'self' {frontend}; base-uri 'none'; frame-ancestors 'none'"
    )


@router.get("/subscription/{token}")
def fake_recurring_page(
    provider: FakeProvider, token: Annotated[str, Path(min_length=32, max_length=32)]
) -> HTMLResponse:
    order = provider.recurring_order(token)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    html = _RECURRING_PAGE.format(
        reference=escape(order.reference),
        # Pasar de pago manual a automatica solo verifica la tarjeta: no cobra.
        what="Cada renovación (hoy no se cobra)" if order.setup_only else "Primer pago",
        amount=f"{order.amount_cents // 100}.{order.amount_cents % 100:02d}",
        currency=escape(order.currency),
        action=escape(f"{provider.api_base_url}/dev/fake-checkout/subscription/{token}", quote=True),
    )
    return HTMLResponse(html, headers={"Content-Security-Policy": _page_csp()})


@router.post("/subscription/{token}")
def fake_recurring_resolve(
    provider: FakeProvider,
    token: Annotated[str, Path(min_length=32, max_length=32)],
    outcome: Annotated[Literal["approved", "approved_declining", "declined"], Form()],
) -> RedirectResponse:
    order = provider.recurring_order(token)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    redirect_url = order.url_ko if outcome == "declined" else order.url_ok
    _check_redirect(redirect_url)
    provider.resolve_recurring(token, outcome)
    return RedirectResponse(redirect_url, status_code=status.HTTP_303_SEE_OTHER)


# ---------- Cambio de la tarjeta de una suscripcion ----------

_CARD_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Pasarela simulada</title></head>
<body style="font-family:sans-serif;max-width:32rem;margin:3rem auto;padding:0 1rem;">
<h1>Pasarela simulada: cambiar la tarjeta</h1>
<p><strong>Solo desarrollo y pruebas. Aquí no se cobra nada.</strong></p>
<form method="post" action="{action}">
<button name="outcome" value="approved">Guardar la tarjeta</button>
<button name="outcome" value="approved_declining">Guardar una tarjeta que rechaza los cobros</button>
</form>
</body></html>"""


@router.get("/card/{token}")
def fake_card_page(
    provider: FakeProvider, token: Annotated[str, Path(min_length=32, max_length=32)]
) -> HTMLResponse:
    if token not in provider.card_changes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    action = escape(f"{provider.api_base_url}/dev/fake-checkout/card/{token}", quote=True)
    return HTMLResponse(_CARD_PAGE.format(action=action), headers={"Content-Security-Policy": _page_csp()})


@router.post("/card/{token}")
def fake_card_resolve(
    provider: FakeProvider,
    token: Annotated[str, Path(min_length=32, max_length=32)],
    outcome: Annotated[Literal["approved", "approved_declining"], Form()],
) -> RedirectResponse:
    if provider.resolve_card_change(token, outcome) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    # Como Tipster Page: de vuelta a la cuenta, que lee la tarjeta nueva.
    return RedirectResponse(
        f"{get_settings().frontend_base_url.rstrip('/')}/cuenta?tarjeta=guardada",
        status_code=status.HTTP_303_SEE_OTHER,
    )
