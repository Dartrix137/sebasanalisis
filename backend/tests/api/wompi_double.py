"""Doble de Wompi para los tests de API.

El proveedor es el `WompiProvider` de verdad, con llaves de prueba y un
transporte HTTP que responde desde memoria: ningun test sale a la red, y aun
asi pasan por la verificacion de firma y la lectura de respuestas reales.

Las rutas y los cuerpos son los de la documentacion de Wompi consultada el
2026-10-13 (las URL estan en `app/payments/wompi.py`).
"""

import json
import uuid

import httpx

from app.models import Payment
from app.payments.wompi import WompiProvider, event_checksum

EVENTS_SECRET = "test_events_solo-para-tests"
INTEGRITY_SECRET = "test_integrity_solo-para-tests"
PUBLIC_KEY = "pub_test_solo-para-tests"
PRIVATE_KEY = "prv_test_solo-para-tests"

# Tokens que "devuelve el widget". El de `rechazado` no sirve para guardar el medio.
TOKEN_TARJETA = "tok_test_tarjeta"
TOKEN_NEQUI = "nequi_test_token"
TOKEN_RECHAZADO = "tok_test_que_wompi_no_acepta"
ACEPTACION = "eyJ.aceptacion.test"
DATOS_PERSONALES = "eyJ.datos-personales.test"


class Wompi:
    """Lo que Wompi "sabe" durante un test: transacciones y fuentes de pago."""

    def __init__(self) -> None:
        self.transactions: dict[str, dict] = {}
        self.sources: dict[str, dict] = {}
        self.caido = False
        #: Solo falla el cobro (POST /transactions); lo demas responde.
        self.cobro_caido = False
        self.consultas = 0
        #: Lo que respondera el proximo cobro a una fuente de pago.
        self.estado_del_cobro = "APPROVED"
        #: Los cuerpos que llegaron a POST /transactions y /payment_sources.
        self.cobros: list[dict] = []
        self.fuentes_pedidas: list[dict] = []
        self.provider = WompiProvider(
            public_key=PUBLIC_KEY,
            private_key=PRIVATE_KEY,
            events_secret=EVENTS_SECRET,
            integrity_secret=INTEGRITY_SECRET,
            api_base_url="https://sandbox.wompi.co/v1",
            environment="sandbox",
            transport=httpx.MockTransport(self._handle),
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if self.caido:
            raise httpx.ConnectError("sin red")
        path = request.url.path.removeprefix("/v1")
        privada = request.headers.get("Authorization") == f"Bearer {PRIVATE_KEY}"

        if request.method == "GET" and path == "/merchants/info":
            assert request.headers["x-merchant-public-key"] == PUBLIC_KEY
            return httpx.Response(
                200,
                json={
                    "data": {
                        "presigned_acceptance": {
                            "acceptance_token": ACEPTACION,
                            "permalink": "https://wompi.example/terminos.pdf",
                            "type": "END_USER_POLICY",
                        },
                        "presigned_personal_data_auth": {
                            "acceptance_token": DATOS_PERSONALES,
                            "permalink": "https://wompi.example/datos.pdf",
                            "type": "PERSONAL_DATA_AUTH",
                        },
                    }
                },
            )

        if request.method == "POST" and path == "/payment_sources":
            assert privada, "la fuente de pago se crea con la llave privada"
            body = json.loads(request.content)
            self.fuentes_pedidas.append(body)
            if body["token"] == TOKEN_RECHAZADO:
                return httpx.Response(422, json={"error": {"type": "INPUT_VALIDATION_ERROR"}})
            source_id = str(3000 + len(self.sources))
            tarjeta = body["type"] == "CARD"
            self.sources[source_id] = body
            return httpx.Response(
                201,
                json={
                    "data": {
                        "id": int(source_id),
                        "type": body["type"],
                        "status": "AVAILABLE",
                        "public_data": (
                            {"type": "CARD", "brand": "VISA", "last_four": "4242", "bin": "424242"}
                            if tarjeta
                            else {"type": "NEQUI", "phone_number": "3991111111"}
                        ),
                    }
                },
            )

        if request.method == "POST" and path == "/transactions":
            assert privada, "el cobro se hace con la llave privada"
            if self.cobro_caido:
                raise httpx.ConnectError("sin red")
            body = json.loads(request.content)
            self.cobros.append(body)
            tx_id = f"tx-{uuid.uuid4().hex[:12]}"
            status = self.estado_del_cobro
            self.transactions[tx_id] = {
                "id": tx_id,
                "reference": body["reference"],
                "status": status,
                "amount_in_cents": body["amount_in_cents"],
                "currency": body["currency"],
                "status_message": None if status in ("APPROVED", "PENDING") else "Fondos insuficientes",
            }
            return httpx.Response(201, json={"data": self.transactions[tx_id]})

        if request.method == "GET" and path.startswith("/transactions/"):
            self.consultas += 1
            data = self.transactions.get(path.rsplit("/", 1)[-1])
            if data is None or not privada:
                return httpx.Response(404, json={"error": {"type": "NOT_FOUND_ERROR"}})
            return httpx.Response(200, json={"data": data})

        return httpx.Response(404, json={"error": {"type": "NOT_FOUND_ERROR"}})

    def transaccion(self, payment: Payment | None, status: str, **cambios) -> str:
        """Anota una transaccion para un pago y devuelve su id."""
        tx_id = f"tx-{uuid.uuid4().hex[:12]}"
        self.transactions[tx_id] = {
            "id": tx_id,
            "reference": payment.reference if payment else f"AJENA-{uuid.uuid4().hex[:8]}",
            "status": status,
            "amount_in_cents": payment.amount_cents if payment else 123_400,
            "currency": payment.currency if payment else "COP",
            "status_message": None if status == "APPROVED" else "Fondos insuficientes",
            **cambios,
        }
        return tx_id

    def resolver(self, tx_id: str, status: str) -> None:
        """Una transaccion que estaba pendiente termina."""
        self.transactions[tx_id]["status"] = status
        self.transactions[tx_id]["status_message"] = (
            None if status == "APPROVED" else "Fondos insuficientes"
        )

    def evento(self, tx_id: str, *, status: str | None = None, timestamp: int = 1_760_000_000) -> dict:
        """Un `transaction.updated` firmado como lo firma Wompi."""
        tx = self.transactions.get(tx_id, {})
        evento = {
            "event": "transaction.updated",
            "data": {
                "transaction": {
                    "id": tx_id,
                    "status": status or tx.get("status", "APPROVED"),
                    "amount_in_cents": tx.get("amount_in_cents", 1),
                    "reference": tx.get("reference", "x"),
                    "currency": "COP",
                }
            },
            "environment": "test",
            "signature": {
                "properties": [
                    "transaction.id",
                    "transaction.status",
                    "transaction.amount_in_cents",
                ],
                "checksum": "",
            },
            "timestamp": timestamp,
            "sent_at": "2026-10-13T15:00:00.000Z",
        }
        evento["signature"]["checksum"] = event_checksum(evento, EVENTS_SECRET)
        return evento
