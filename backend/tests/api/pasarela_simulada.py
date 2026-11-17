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
    ChargePeriod,
    PaymentMethodOption,
    PaymentProviderError,
    PaymentSource,
    ProviderTransaction,
    RecurringOrder,
    RecurringStart,
    TransactionStatus,
)
from app.payments.fake import FAKE_SIGNATURE, FAKE_SIGNATURE_HEADER, FakePaymentProvider

NOMBRE = "fake"

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
        #: Lo que llego a `charge`, mas el primer cobro de cada alta pagada.
        self.cobros: list[dict[str, Any]] = []
        #: El periodo de cada cobro, en el mismo orden que `cobros`.
        self.periodos: list[ChargePeriod] = []
        self._fuentes: dict[str, str] = {}
        #: Las altas de renovacion automatica que se abrieron.
        self.altas: list[RecurringOrder] = []
        #: Solo falla el alta de la renovacion automatica.
        self.alta_caida = False

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

    def completar_alta(self, checkout_url: str, outcome: str = "approved") -> ProviderTransaction:
        """El cliente termino en la pagina del alta de la renovacion automatica:
        `approved`, `approved_declining` (una tarjeta que rechaza las
        renovaciones) o `declined`."""
        token = checkout_url.rsplit("/", 1)[1]
        order = self.recurring_order(token)
        transaction = self.resolve_recurring(token, outcome)
        assert order is not None and transaction is not None, checkout_url
        if transaction.saved_source is not None and not order.setup_only:
            # El primer periodo se cobro en esa pagina: cuenta entre los cobros.
            self.cobros.append(
                {
                    "reference": order.reference,
                    "amount_cents": order.amount_cents,
                    "currency": order.currency,
                    "customer_email": order.email,
                    "source_id": transaction.saved_source.id,
                    "source_type": transaction.saved_source.type,
                }
            )
        return transaction

    def start_recurring(self, order: RecurringOrder) -> RecurringStart:
        self._red()
        if self.alta_caida:
            raise PaymentProviderError("La pasarela no respondio")
        self.altas.append(order)
        return super().start_recurring(order)

    def resolve_recurring(self, token: str, outcome: str) -> ProviderTransaction | None:
        transaction = super().resolve_recurring(token, outcome)
        if transaction is not None and transaction.saved_source is not None:
            # Ids en serie, como los del medio tokenizado: el primero es "3000".
            source = replace(transaction.saved_source, id=str(3000 + len(self._fuentes)))
            transaction = replace(transaction, saved_source=source)
            self.transactions[transaction.id] = transaction
            self._fuentes[source.id] = source.type
            if source.agreement_id is not None:
                self.agreements[source.agreement_id] = source
        return transaction

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

    def card_change_url(self, source: PaymentSource, *, recovery: bool, reference: str) -> str:
        self._red()
        return super().card_change_url(source, recovery=recovery, reference=reference)

    def resolve_card_change(self, token: str, outcome: str) -> PaymentSource | None:
        """La tarjeta nueva, con el siguiente id de la serie ("3001", "3002"...)."""
        source = super().resolve_card_change(token, outcome)
        if source is None:
            return None
        source = replace(source, id=str(3000 + len(self._fuentes)))
        self._fuentes[source.id] = source.type
        if source.agreement_id is not None:
            self.agreements[source.agreement_id] = source
        return source

    def charge(
        self,
        *,
        reference: str,
        amount_cents: int,
        currency: str,
        customer_email: str,
        source: PaymentSource,
        period: ChargePeriod,
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
        self.periodos.append(period)
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
