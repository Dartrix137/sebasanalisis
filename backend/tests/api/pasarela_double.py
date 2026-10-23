"""Doble de la pasarela de pagos para los tests de API.

Transitorio (Fase 5, paso 5.1): Wompi salio del proyecto y la pasarela nueva
(Tipster Page, paso 5.3) todavia no tiene documentacion. Mientras tanto, los
tests de pagos corren contra esta pasarela de mentira, que cumple
`PaymentProvider` en memoria. Con la pasarela nueva vuelve la regla de antes: el
proveedor de verdad con un transporte HTTP simulado, y este archivo se borra.

Lo que si conserva de una pasarela real es lo que prueban los casos de §3.9:

- Los eventos van firmados con HMAC-SHA256 sobre su propio contenido. Uno sin
  firma, con otra firma o alterado despues de firmado no pasa.
- Cada evento lleva un id estable entre reintentos: el mismo evento reenviado
  trae el mismo id, y otro `timestamp` es otro evento.
- La transaccion solo se cree cuando sale de `fetch_transaction`, que cuenta las
  reconsultas y puede "caerse".
- Habla su propio vocabulario de estados (`APPROVED`, `DECLINED`...) y lo
  traduce, como lo haria el proveedor de verdad.
"""

import hashlib
import hmac
import json
import uuid
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from app.models import Payment
from app.payments.base import (
    Acceptance,
    PaymentProviderError,
    PaymentSource,
    PaymentSourceRejected,
    PaymentSourceType,
    ProviderEvent,
    ProviderTransaction,
    TokenizerInfo,
    TransactionStatus,
    unverified_event,
)

NOMBRE = "pasarela"
SECRETO_DE_EVENTOS = "secreto-de-eventos-solo-para-tests"
CHECKOUT_URL = "https://pasarela.test/pagar"

# Tokens que el navegador obtiene de la pasarela. El de `rechazado` no sirve para guardar el medio.
TOKEN_TARJETA = "tok_test_tarjeta"
TOKEN_NEQUI = "nequi_test_token"
TOKEN_RECHAZADO = "tok_test_que_la_pasarela_no_acepta"
ACEPTACION = "aceptacion-test"
DATOS_PERSONALES = "datos-personales-test"

_ESTADOS: dict[str, TransactionStatus] = {
    "PENDING": "pending",
    "APPROVED": "approved",
    "DECLINED": "declined",
    "VOIDED": "voided",
    "ERROR": "error",
}


def firma(evento: Mapping[str, Any]) -> str:
    """HMAC-SHA256, en hexadecimal, del evento sin su campo `firma`."""
    cuerpo = {k: v for k, v in evento.items() if k != "firma"}
    canonico = json.dumps(cuerpo, sort_keys=True, separators=(",", ":"))
    return hmac.new(SECRETO_DE_EVENTOS.encode(), canonico.encode(), hashlib.sha256).hexdigest()


def _mensaje(status: str) -> str | None:
    return None if status in ("APPROVED", "PENDING") else "Fondos insuficientes"


class Pasarela:
    """Lo que la pasarela "sabe" durante un test: transacciones y fuentes de pago."""

    def __init__(self) -> None:
        self.transactions: dict[str, dict[str, Any]] = {}
        self.sources: dict[str, dict[str, Any]] = {}
        #: Sin red: ninguna llamada responde.
        self.caido = False
        #: Solo falla el cobro; lo demas responde.
        self.cobro_caido = False
        self.consultas = 0
        #: Lo que respondera el proximo cobro a una fuente de pago.
        self.estado_del_cobro = "APPROVED"
        #: Lo que llego a `charge` y a `create_payment_source`.
        self.cobros: list[dict[str, Any]] = []
        self.fuentes_pedidas: list[dict[str, Any]] = []
        self.provider = _Proveedor(self)

    def transaccion(self, payment: Payment | None, status: str, **cambios: Any) -> str:
        """Anota una transaccion para un pago y devuelve su id."""
        tx_id = f"tx-{uuid.uuid4().hex[:12]}"
        self.transactions[tx_id] = {
            "id": tx_id,
            "reference": payment.reference if payment else f"AJENA-{uuid.uuid4().hex[:8]}",
            "status": status,
            "amount_cents": payment.amount_cents if payment else 123_400,
            "currency": payment.currency if payment else "COP",
            "status_message": _mensaje(status),
            **cambios,
        }
        return tx_id

    def resolver(self, tx_id: str, status: str) -> None:
        """Una transaccion que estaba pendiente termina."""
        self.transactions[tx_id]["status"] = status
        self.transactions[tx_id]["status_message"] = _mensaje(status)

    def evento(
        self, tx_id: str, *, status: str | None = None, timestamp: int = 1_760_000_000
    ) -> dict[str, Any]:
        """Un evento firmado de que la transaccion cambio."""
        tx = self.transactions.get(tx_id, {})
        estado = status or tx.get("status", "APPROVED")
        evento: dict[str, Any] = {
            # Estable entre reintentos: sale de la transaccion, su estado y la hora.
            "id": hashlib.sha256(f"{tx_id}|{estado}|{timestamp}".encode()).hexdigest()[:32],
            "event": "transaction.updated",
            "data": {
                "transaction": {
                    "id": tx_id,
                    "status": estado,
                    "amount_cents": tx.get("amount_cents", 1),
                    "reference": tx.get("reference", "x"),
                    "currency": "COP",
                    # Lo que la pasarela manda de mas y no hace falta guardar para siempre.
                    "customer_email": "cliente@ejemplo.com",
                    "payment_method": {"type": "CARD", "last_four": "4242"},
                }
            },
            "timestamp": timestamp,
        }
        evento["firma"] = firma(evento)
        return evento


class _Proveedor:
    """La pasarela de mentira detras de `PaymentProvider`."""

    name = NOMBRE
    enabled = True

    def __init__(self, pasarela: Pasarela) -> None:
        self._p = pasarela

    def _red(self) -> None:
        if self._p.caido:
            raise PaymentProviderError("La pasarela no respondio")

    def describe(self) -> str:
        return "pasarela de pruebas (en memoria)"

    def checkout_url(
        self,
        *,
        reference: str,
        amount_cents: int,
        currency: str,
        redirect_url: str,
        customer_email: str,
    ) -> str:
        params = {
            "reference": reference,
            "amount_cents": str(amount_cents),
            "currency": currency,
            "redirect_url": redirect_url,
        }
        return f"{CHECKOUT_URL}?{urlencode(params)}"

    def parse_event(self, body: bytes, headers: Mapping[str, str]) -> ProviderEvent:
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            payload = None
        if not isinstance(payload, dict):
            return unverified_event(self.name, body, None)
        recibida = payload.get("firma")
        event_id = payload.get("id")
        if (
            not isinstance(recibida, str)
            or not isinstance(event_id, str)
            or not hmac.compare_digest(recibida.encode(), firma(payload).encode())
        ):
            return unverified_event(self.name, body, payload)
        data = payload.get("data")
        transaction = data.get("transaction") if isinstance(data, dict) else None
        transaction = transaction if isinstance(transaction, dict) else {}
        transaction_id = transaction.get("id")
        status = transaction.get("status")
        event_type = payload.get("event")
        return ProviderEvent(
            event_id=f"{self.name}:{event_id}",
            event_type=event_type if isinstance(event_type, str) else "unknown",
            signature_verified=True,
            transaction_id=transaction_id if isinstance(transaction_id, str) else None,
            status=status if isinstance(status, str) else "unknown",
            payload=payload,
        )

    def fetch_transaction(self, transaction_id: str) -> ProviderTransaction | None:
        self._red()
        self._p.consultas += 1
        data = self._p.transactions.get(transaction_id)
        return _transaccion(data) if data is not None else None

    def tokenizer(self) -> TokenizerInfo | None:
        return TokenizerInfo(kind="fake")

    def acceptance(self) -> Acceptance:
        self._red()
        return Acceptance(
            acceptance_token=ACEPTACION,
            terms_url="https://pasarela.test/terminos.pdf",
            personal_data_token=DATOS_PERSONALES,
            personal_data_url="https://pasarela.test/datos.pdf",
        )

    def create_payment_source(
        self,
        *,
        source_type: PaymentSourceType,
        token: str,
        customer_email: str,
        acceptance_token: str,
        personal_data_token: str,
    ) -> PaymentSource:
        self._red()
        pedida = {
            "type": source_type,
            "token": token,
            "customer_email": customer_email,
            "acceptance_token": acceptance_token,
            "personal_data_token": personal_data_token,
        }
        self._p.fuentes_pedidas.append(pedida)
        if token == TOKEN_RECHAZADO:
            raise PaymentSourceRejected("La pasarela no acepto el medio de pago")
        source_id = str(3000 + len(self._p.sources))
        self._p.sources[source_id] = pedida
        tarjeta = source_type == "CARD"
        return PaymentSource(
            id=source_id,
            type=source_type,
            # Como la pasarela anterior: la fuente trae los ultimos cuatro, no la marca.
            brand=None,
            last4="4242" if tarjeta else None,
        )

    def charge(
        self,
        *,
        reference: str,
        amount_cents: int,
        currency: str,
        customer_email: str,
        source: PaymentSource,
    ) -> ProviderTransaction:
        self._red()
        if self._p.cobro_caido:
            raise PaymentProviderError("La pasarela no respondio")
        self._p.cobros.append(
            {
                "reference": reference,
                "amount_cents": amount_cents,
                "currency": currency,
                "customer_email": customer_email,
                "source_id": source.id,
                "source_type": source.type,
            }
        )
        tx_id = f"tx-{uuid.uuid4().hex[:12]}"
        status = self._p.estado_del_cobro
        data: dict[str, Any] = {
            "id": tx_id,
            "reference": reference,
            "status": status,
            "amount_cents": amount_cents,
            "currency": currency,
            "status_message": _mensaje(status),
        }
        if self._p.sources.get(source.id, {}).get("type") == "CARD":
            data["card_brand"], data["card_last4"] = "VISA", "4242"
        self._p.transactions[tx_id] = data
        return _transaccion(data)


def _transaccion(data: dict[str, Any]) -> ProviderTransaction:
    return ProviderTransaction(
        id=data["id"],
        reference=data["reference"],
        status=_ESTADOS[data["status"]],
        amount_cents=data["amount_cents"],
        currency=data["currency"],
        status_message=data.get("status_message"),
        card_brand=data.get("card_brand"),
        card_last4=data.get("card_last4"),
    )
