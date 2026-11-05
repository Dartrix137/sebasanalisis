"""La pasarela simulada de la aplicacion, con controles para los tests.

Tipster Page no guarda medios de pago ni anula pagos por la API (2026-11-03).
Los tests de lo que solo existe con una pasarela que si lo hace (la renovacion
automatica, el cambio de medio de pago y la anulacion de un pago aprobado)
corren sobre `FakePaymentProvider`, la pasarela simulada que ya usan el
desarrollo y Playwright (decidido por el usuario el 2026-11-04). Esta subclase
solo le agrega lo que un test necesita mirar o forzar: los cobros que llegaron,
el resultado del proximo cobro y una caida de la red.

El pago manual con Tipster Page se prueba con su proveedor de verdad sobre un
transporte HTTP simulado (`tipster_sandbox.py`).
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field, replace
from typing import Any

from app.models import Payment
from app.payments.base import (
    PaymentMethodOption,
    PaymentProviderError,
    PaymentSource,
    PaymentSourceRejected,
    PaymentSourceType,
    ProviderTransaction,
    TransactionStatus,
)
from app.payments.fake import FAKE_SIGNATURE, FAKE_SIGNATURE_HEADER, FakePaymentProvider

NOMBRE = "fake"

# Tokens que el navegador obtiene del selector simulado. El de `rechazado` no
# sirve para guardar el medio.
TOKEN_TARJETA = "tok_test_tarjeta"
TOKEN_OTRO_MEDIO = "tok_test_otro_medio"
TOKEN_RECHAZADO = "tok_test_que_la_pasarela_no_acepta"

#: El vocabulario de estados de la pasarela simulada en los tests.
_ESTADOS: dict[str, TransactionStatus] = {
    "PENDING": "pending",
    "APPROVED": "approved",
    "DECLINED": "declined",
    "VOIDED": "voided",
    "ERROR": "error",
}


@dataclass(frozen=True)
class Aviso:
    """Un webhook listo para mandar: el cuerpo y sus cabeceras."""

    body: bytes
    headers: dict[str, str] = field(default_factory=dict)


def _mensaje(status: str) -> str | None:
    return None if status in ("APPROVED", "PENDING") else "Fondos insuficientes"


class PasarelaSimulada(FakePaymentProvider):
    def __init__(self) -> None:
        super().__init__(api_base_url="http://testserver")
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
        self._fuentes: dict[str, str] = {}

    @property
    def provider(self) -> "PasarelaSimulada":
        return self

    def _red(self) -> None:
        if self.caido:
            raise PaymentProviderError("La pasarela no respondio")

    # ---- lo que hace un test

    def transaccion(self, payment: Payment | None, status: str, **cambios: Any) -> str:
        """Anota una transaccion para un pago y devuelve su id."""
        tx_id = f"tx-{uuid.uuid4().hex[:12]}"
        datos: dict[str, Any] = {
            "id": tx_id,
            "reference": payment.reference if payment else f"AJENA-{uuid.uuid4().hex[:8]}",
            "status": _ESTADOS[status],
            "amount_cents": payment.amount_cents if payment else 3200,
            "currency": payment.currency if payment else "EUR",
            "status_message": _mensaje(status),
        }
        datos.update(cambios)
        self.transactions[tx_id] = ProviderTransaction(**datos)
        return tx_id

    def resolver(self, tx_id: str, status: str) -> None:
        """Una transaccion que estaba pendiente termina."""
        self.transactions[tx_id] = replace(
            self.transactions[tx_id], status=_ESTADOS[status], status_message=_mensaje(status)
        )

    def evento(self, tx_id: str, *, status: str | None = None, timestamp: int = 1_760_000_000) -> Aviso:
        """Un aviso autentico de que la transaccion cambio."""
        estado = status
        if estado is None:
            tx = self.transactions.get(tx_id)
            estado = next((k for k, v in _ESTADOS.items() if tx and v == tx.status), "APPROVED")
        cuerpo = {
            # Estable entre reintentos: sale de la transaccion, su estado y la hora.
            "id": hashlib.sha256(f"{tx_id}|{estado}|{timestamp}".encode()).hexdigest()[:32],
            "transaction_id": tx_id,
            "status": estado,
            "timestamp": timestamp,
            # Lo que una pasarela manda de mas y no hace falta guardar para siempre.
            "customer_email": "cliente@ejemplo.com",
            "payment_method": {"type": "CARD", "last_four": "4242"},
        }
        return Aviso(
            body=json.dumps(cuerpo).encode(),
            headers={FAKE_SIGNATURE_HEADER: FAKE_SIGNATURE},
        )

    def aprobar(self, payment: Payment) -> Aviso:
        return self.evento(self.transaccion(payment, "APPROVED"))

    # ---- la pasarela

    def payment_methods(self, country: str | None) -> list[PaymentMethodOption]:
        # La misma llave que la tarjeta de Tipster Page: los ayudantes de los
        # tests abren el pago manual igual con las dos.
        return [
            PaymentMethodOption(
                key="cardtpv", name="Tarjeta simulada", logo_url=None,
                min_cents=100, max_cents=40_000, currency="EUR",
            )
        ]

    def fetch_transaction(self, transaction_id: str) -> ProviderTransaction | None:
        self._red()
        self.consultas += 1
        return super().fetch_transaction(transaction_id)

    def create_payment_source(
        self, *, source_type: PaymentSourceType, token: str, customer_email: str
    ) -> PaymentSource:
        self._red()
        self.fuentes_pedidas.append(
            {"type": source_type, "token": token, "customer_email": customer_email}
        )
        if token == TOKEN_RECHAZADO:
            raise PaymentSourceRejected("La pasarela no acepto el medio de pago")
        source_id = str(3000 + len(self._fuentes))
        self._fuentes[source_id] = source_type
        tarjeta = source_type == "CARD"
        # La fuente trae los ultimos cuatro, no la marca: esa llega con el cobro.
        return PaymentSource(id=source_id, type=source_type, brand=None, last4="4242" if tarjeta else None)

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
        if self.cobro_caido:
            raise PaymentProviderError("La pasarela no respondio")
        self.cobros.append(
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
        tarjeta = self._fuentes.get(source.id) == "CARD"
        transaction = ProviderTransaction(
            id=tx_id,
            reference=reference,
            status=_ESTADOS[self.estado_del_cobro],
            amount_cents=amount_cents,
            currency=currency,
            status_message=_mensaje(self.estado_del_cobro),
            card_brand="VISA" if tarjeta else None,
            card_last4="4242" if tarjeta else None,
        )
        self.transactions[tx_id] = transaction
        return transaction
