"""Consulta y guarda las tasas de cambio de la factura (docs/PLATAFORMA_COMPLETA.md
§3.17, "Paso 5.4", punto 5; Fase 5, paso 5.4).

Las reglas (que fuente, como se elige la tasa de un dia) son de
`billing/exchange_rates.py`, que es puro. Aqui se consulta la red y se guarda
en `exchange_rates`.

Fuentes, leidas el 2026-11-09:

- TRM: `GET https://www.datos.gov.co/resource/32sa-8pi3.json` con un filtro
  SoQL (`$where`) por vigencia. La consulta publica no pide llave. Con
  `DATOS_GOV_APP_TOKEN` va en la cabecera `X-App-Token`, que la documentacion
  de Socrata (la plataforma de datos.gov.co) da como la forma preferida:
  `https://dev.socrata.com/docs/app-tokens.html`. Sin token, el limite es por
  IP y compartido; con token, propio. Un token invalido responde 403
  "Invalid app_token specified" (probado el 2026-11-09). El "secret token" de
  la cuenta es solo para OAuth y no se usa.
- BCE: `GET https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml`,
  sin llave (`https://www.ecb.europa.eu/stats/policy_and_exchange_rates/
  euro_reference_exchange_rates/html/index.en.html`).

Una tasa guardada no se reemplaza: si la fuente la cambiara despues, una
factura ya preparada no cambia, y la fila deja constancia de lo que se uso.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.billing import fx
from app.billing.exchange_rates import (
    RatePeriod,
    RateSourceError,
    ecb_for,
    parse_ecb_xml,
    parse_trm_rows,
    trm_for,
)
from app.core.config import Settings, get_settings
from app.models import ExchangeRate

logger = logging.getLogger(__name__)

TRM_URL = "https://www.datos.gov.co/resource/32sa-8pi3.json"
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class RateUnavailable(Exception):
    """La fuente no respondio o respondio algo que no se pudo leer."""


@dataclass(frozen=True)
class DayRates:
    """Las tasas de un dia, con la fila de cada una (vigencia y fuente)."""

    trm: RatePeriod
    eur_usd: RatePeriod | None

    def as_fx(self) -> fx.Rates:
        return fx.Rates(
            eur_usd=self.eur_usd.value if self.eur_usd else None, usd_cop=self.trm.value
        )


class RateSources:
    """Las dos fuentes por HTTP. Los tests le pasan un `httpx.MockTransport`."""

    def __init__(
        self,
        *,
        app_token: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        # El token es de datos.gov.co: va solo en sus peticiones, nunca al BCE.
        self._app_token = app_token
        self._client = httpx.Client(timeout=_TIMEOUT, transport=transport)

    def _request(self, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.get(url, **kwargs)
        except httpx.HTTPError as exc:
            raise RateUnavailable(f"{url}: {type(exc).__name__}") from exc

    def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        response = self._request(url, **kwargs)
        if response.status_code != 200:
            raise RateUnavailable(f"{url}: HTTP {response.status_code}")
        return response

    def _trm_get(self, params: dict[str, str]) -> httpx.Response:
        """La consulta a datos.gov.co, con el token si lo hay. El token es
        opcional: si datos.gov.co lo rechaza (403 "Invalid app_token
        specified", p. ej. porque se puso una API key en su lugar), la consulta
        se repite sin el y queda un aviso, en vez de dejar la factura sin TRM."""
        headers = {"Accept": "application/json"}
        if self._app_token:
            response = self._request(
                TRM_URL, params=params, headers={**headers, "X-App-Token": self._app_token}
            )
            if response.status_code == 403 and "app_token" in response.text:
                logger.warning(
                    "datos.gov.co rechazo DATOS_GOV_APP_TOKEN: la TRM se consulta sin token"
                )
            elif response.status_code != 200:
                raise RateUnavailable(f"{TRM_URL}: HTTP {response.status_code}")
            else:
                return response
        return self._get(TRM_URL, params=params, headers=headers)

    def trm_covering(self, day: date) -> list[RatePeriod]:
        """Las filas de la TRM cuya vigencia cubre el dia (normalmente una)."""
        stamp = f"{day.isoformat()}T00:00:00"
        response = self._trm_get(
            {"$where": f"vigenciadesde <= '{stamp}' AND vigenciahasta >= '{stamp}'"}
        )
        try:
            return parse_trm_rows(response.json())
        except (ValueError, RateSourceError) as exc:
            raise RateUnavailable(f"TRM: {exc}") from exc

    def ecb_recent(self) -> list[RatePeriod]:
        """Los ultimos 90 dias del BCE."""
        response = self._get(ECB_URL, headers={"Accept": "application/xml"})
        try:
            return parse_ecb_xml(response.content)
        except RateSourceError as exc:
            raise RateUnavailable(f"BCE: {exc}") from exc


def build_sources(settings: Settings | None = None) -> RateSources:
    settings = settings or get_settings()
    return RateSources(app_token=settings.datos_gov_app_token)


def _stored(db: Session, pair: str, start: date, end: date) -> list[RatePeriod]:
    rows = db.scalars(
        select(ExchangeRate).where(
            ExchangeRate.pair == pair,
            ExchangeRate.valid_to >= start,
            ExchangeRate.valid_from <= end,
        )
    )
    return [
        RatePeriod(
            pair=row.pair,  # type: ignore[arg-type]
            valid_from=row.valid_from,
            valid_to=row.valid_to,
            value=row.rate,
            source=row.source,
        )
        for row in rows
    ]


def _store(db: Session, periods: list[RatePeriod]) -> None:
    """Guarda las que no estaban. Una que ya estaba no se toca."""
    if not periods:
        return
    stmt = insert(ExchangeRate).values(
        [
            {
                "pair": p.pair,
                "valid_from": p.valid_from,
                "valid_to": p.valid_to,
                "rate": p.value,
                "source": p.source,
            }
            for p in periods
        ]
    )
    db.execute(stmt.on_conflict_do_nothing(constraint="uq_exchange_rates_pair_valid_from"))
    db.flush()


def rates_for(
    db: Session, day: date, currency: str, sources: RateSources
) -> DayRates | None:
    """Las tasas que convierten un pago del `day` en `currency` a pesos, o
    `None` si alguna todavia no esta publicada (la factura espera).

    Primero mira lo guardado; solo consulta la fuente de lo que falta, y guarda
    lo que trae. No hace commit. `RateUnavailable` si una fuente falla.
    """
    if currency == fx.FUNCTIONAL_CURRENCY:
        raise ValueError("Un pago en pesos no necesita tasas")
    if currency not in ("USD", "EUR"):
        raise ValueError(f"No se sabe convertir {currency} a pesos")

    trm = trm_for(day, _stored(db, "USD/COP", day, day))
    if trm is None:
        _store(db, sources.trm_covering(day))
        trm = trm_for(day, _stored(db, "USD/COP", day, day))
    if trm is None:
        return None
    if currency == "USD":
        return DayRates(trm=trm, eur_usd=None)

    window_start = day - timedelta(days=30)
    window_end = day + timedelta(days=30)
    stored = _stored(db, "EUR/USD", window_start, window_end)
    # Lo guardado alcanza solo si trae el dia o uno posterior: si no, puede
    # faltar la del ultimo dia habil (guardada antes de que saliera), y un
    # sabado tomaria la del jueves en vez de la del viernes.
    if not any(p.valid_from >= day for p in stored):
        _store(db, sources.ecb_recent())
        stored = _stored(db, "EUR/USD", window_start, window_end)
    try:
        eur_usd = ecb_for(day, stored)
    except RateSourceError as exc:
        raise RateUnavailable(f"BCE: {exc}") from exc
    if eur_usd is None:
        return None
    return DayRates(trm=trm, eur_usd=eur_usd)


@lru_cache
def get_rate_sources() -> RateSources:
    """Las fuentes de la aplicacion. Los tests la sustituyen."""
    return build_sources()
