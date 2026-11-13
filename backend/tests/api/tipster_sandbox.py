"""Tipster Page simulado a nivel HTTP, para los tests.

El `TipsterPageProvider` de verdad habla con esto a traves de un
`httpx.MockTransport`: ningun test sale a la red, y aun asi cada llamada pasa
por las cabeceras, la firma de la orden, la lectura del aviso y la reconsulta
del proveedor real.

Lo que se comporta como dice el manual V2 de Tipster Page:

- Las tres llamadas exigen `X-TSPAY-USER` y `Authorization: Bearer` (§4); sin
  ellas, 401.
- `POST /create-order-tspay` verifica `tspay_signature` con su propio calculo
  (§7.1, escrito aqui aparte del de la aplicacion), exige los datos del
  comprador que pide el medio y el pais de un medio local, y responde HTML
  (§7.2). Un `order_id` repetido se acepta y la orden queda con los datos
  nuevos, monto incluido, como en el sandbox (probado el 2026-11-05). La
  aplicacion no repite referencias: una por pago.
- `GET /order-status/{orderId}` responde el monto como un numero JSON, como lo
  serializa JavaScript (§10), o 404.
- `aviso()` arma el cuerpo de la notificacion firmado con §9.1 sobre el monto
  tal como va en el texto (`32`, `12.5`).
"""

import hashlib
import hmac
import json
from decimal import Decimal
from typing import Any

import httpx

from app.models import Payment
from app.payments.tipsterpage import SANDBOX_BASE_URL, TipsterPageProvider

MERCHANT = "TSPAY-TEST-001"
BEARER = "bearer-solo-para-tests"
# Con caracteres que se prestan a errores de comillas, como el de verdad.
SECRETO = 'secreto^(de]{prueba}$"%;con-#signos'

ORDER_FIELDS = (
    "order_id",
    "product_id",
    "product_name",
    "product_description",
    "amount",
    "payment_method",
    "url_ok",
    "url_ko",
    "notification_url",
    "country",
)

#: La pagina que devuelve el sandbox con tarjeta (vista el 2026-11-05), con los
#: valores firmados de Redsys cambiados: un formulario que se envia solo desde
#: un `onload` en linea, sin `<script>`.
PAGINA_REDSYS = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Processing</title></head>
<body onload="document.getElementById('form').submit()">
<p>Loading payment gateway. Please wait, you will be redirected to the bank to complete the payment.</p>
<form action="https://sis-t.redsys.es:25443/sis/realizarPago" method="post" id="form">
<input type="hidden" name="Ds_SignatureVersion" value="HMAC_SHA256_V1">
<input type="hidden" name="Ds_MerchantParameters" value="eyJvcmRlciI6IjEifQ==">
<input type="hidden" name="Ds_Signature" value="abc">
<noscript><input type="submit" value="Pay"></noscript>
</form>
</body>
</html>"""

CATALOGO: list[dict[str, Any]] = [
    {
        "key": "cardtpv",
        "name": "Tarjeta de crédito/débito",
        "provider": "Redsys",
        "translations": {"en": "Credit / debit card"},
        "logoUrl": "https://cdntpfiles86236.tipsterpage.com/images/payment_methods/tarjeta.png",
        "priceMin": 1,
        "priceMax": 400,
        "countries": [],
        "fields": [],
    },
    {
        "key": "bizum",
        "name": "Bizum",
        "provider": "Redsys",
        "translations": {"en": "Bizum"},
        "logoUrl": "https://cdntpfiles86236.tipsterpage.com/images/payment_methods/bizum.png",
        "priceMin": 1,
        "priceMax": 12,
        "countries": ["ES"],
        "fields": [],
    },
    {
        "key": "ebanxpsecolombia",
        "name": "PSE",
        "provider": "Ebanx",
        "translations": {"en": "PSE"},
        "logoUrl": "https://cdntpfiles86236.tipsterpage.com/images/payment_methods/co/pse.png",
        "priceMin": 1,
        "priceMax": 400,
        "countries": ["CO"],
        "fields": ["firstName"],
    },
    {
        "key": "ebanxyapeperu",
        "name": "Yape",
        "provider": "Ebanx",
        "translations": {"en": "Yape"},
        "logoUrl": "https://cdntpfiles86236.tipsterpage.com/images/payment_methods/pe/yape.png",
        "priceMin": 1,
        "priceMax": 400,
        "countries": ["PE"],
        "fields": ["firstName", "phone"],
    },
    # Esta en el catalogo real del sandbox desde la v2.2; es de cripto y no se
    # ofrece (`tipsterpage.EXCLUDED_METHODS`).
    {
        "key": "binancepay",
        "name": "Binance Pay",
        "provider": "IBIS",
        "translations": {"en": "Binance Pay"},
        "logoUrl": "https://cdntpfiles86236.tipsterpage.com/images/payment_methods/binance.png",
        "priceMin": 1,
        "priceMax": 400,
        "countries": [],
        "fields": [],
    },
]


def monto_js(cents: int) -> str:
    """Como serializa JavaScript el monto en euros: `3200` -> `32`, `1250` -> `12.5`."""
    return format((Decimal(cents) / 100).normalize(), "f")


def firma_de_orden(params: dict[str, str]) -> str:
    """Manual §7.1, calculado aqui aparte del de la aplicacion."""
    s = "".join(params.get(k, "") for k in ORDER_FIELDS)
    return hmac.new(SECRETO.encode(), s.encode(), hashlib.sha256).hexdigest()


def firma_de_aviso(paid_status: str, order_id: str, amount: str) -> str:
    """Manual §9.1."""
    s = f"{paid_status}{order_id}{amount}"
    return hmac.new(SECRETO.encode(), s.encode(), hashlib.sha256).hexdigest()


class TipsterSandbox:
    """Lo que Tipster Page "sabe" durante un test: el catalogo y las ordenes."""

    def __init__(self) -> None:
        self.catalogo = [dict(m) for m in CATALOGO]
        #: order_id -> lo que se guardo de la orden y su estado.
        self.ordenes: dict[str, dict[str, Any]] = {}
        #: Los cuerpos de `create-order-tspay` tal como llegaron (con los datos
        #: del comprador): para revisar que viajaron y que la firma es la correcta.
        self.pedidos: list[dict[str, Any]] = []
        #: Sin red: ninguna llamada responde.
        self.caido = False
        #: Forzar la respuesta de la creacion de la orden: (codigo, cuerpo).
        self.respuesta_orden: tuple[int, str] | None = None
        self.pagina = PAGINA_REDSYS
        self.consultas = 0
        self.consultas_de_catalogo = 0
        self.provider = TipsterPageProvider(
            base_url=SANDBOX_BASE_URL,
            merchant_code=MERCHANT,
            auth_bearer=BEARER,
            secret_key=SECRETO,
            transport=httpx.MockTransport(self._responder),
        )

    # ---- lo que hace la pasarela

    def _responder(self, request: httpx.Request) -> httpx.Response:
        if self.caido:
            raise httpx.ConnectError("sin red", request=request)
        if (
            request.headers.get("X-TSPAY-USER") != MERCHANT
            or request.headers.get("Authorization") != f"Bearer {BEARER}"
        ):
            return httpx.Response(401, json={"statusCode": 401, "message": "Unauthorized"})
        path = request.url.path.removeprefix("/tspayv2")
        if request.method == "GET" and path == "/payment-methods":
            return self._catalogo(request)
        if request.method == "POST" and path == "/create-order-tspay":
            return self._crear_orden(request)
        if request.method == "GET" and path.startswith("/order-status/"):
            return self._estado(path.removeprefix("/order-status/"))
        return httpx.Response(404, json={"statusCode": 404, "message": "Not Found"})

    def _catalogo(self, request: httpx.Request) -> httpx.Response:
        self.consultas_de_catalogo += 1
        pais = request.url.params.get("country-code")
        if pais is None:
            return httpx.Response(200, json=self.catalogo)
        if len(pais) != 2 or not pais.isalpha():
            return httpx.Response(400, json={"statusCode": 400, "message": "country-code"})
        pais = pais.upper()
        return httpx.Response(
            200, json=[m for m in self.catalogo if not m["countries"] or pais in m["countries"]]
        )

    def _error(self, mensaje: str) -> httpx.Response:
        return httpx.Response(400, json={"statusCode": 400, "message": mensaje, "error": "Bad Request"})

    def _crear_orden(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.pedidos.append(body)
        if self.respuesta_orden is not None:
            codigo, cuerpo = self.respuesta_orden
            return httpx.Response(codigo, json={"statusCode": codigo, "message": cuerpo})
        firmados = {k: body[k] for k in ORDER_FIELDS if k in body}
        if body.get("tspay_signature") != firma_de_orden(firmados):
            return self._error("Invalid signature")
        metodo = next((m for m in self.catalogo if m["key"] == body.get("payment_method")), None)
        if metodo is None:
            return self._error("Payment method not available")
        if metodo["countries"] and body.get("country") not in metodo["countries"]:
            return self._error("Invalid country")
        if any(not str(body.get(campo, "")).strip() for campo in metodo["fields"]):
            return self._error("Missing buyer field")
        monto = Decimal(body["amount"])
        if not Decimal(metodo["priceMin"]) <= monto <= Decimal(metodo["priceMax"]):
            return self._error("Amount out of range")
        # Como el sandbox (2026-11-05): un `order_id` repetido no se rechaza,
        # la orden se vuelve a crear con los datos nuevos (el monto tambien).
        self.ordenes[body["order_id"]] = {
            "amount": int(monto * 100),
            "paid_order_status": "pending",
            "product_id": body["product_id"],
            "product_name": body["product_name"],
        }
        return httpx.Response(201, text=self.pagina, headers={"Content-Type": "text/html; charset=utf-8"})

    def _estado(self, order_id: str) -> httpx.Response:
        self.consultas += 1
        orden = self.ordenes.get(order_id)
        if orden is None:
            return httpx.Response(404, json={"message": "Order not found", "statusCode": 404})
        # Como lo serializa la pasarela: el monto como numero JSON (`32`, `12.5`).
        texto = (
            f'{{"amount":{orden.get("amount_texto") or monto_js(orden["amount"])},'
            f'"paid_order_status":{json.dumps(orden["paid_order_status"])},'
            f'"product_id":{json.dumps(orden["product_id"])},'
            f'"product_name":{json.dumps(orden["product_name"])}}}'
        )
        return httpx.Response(200, content=texto.encode(), headers={"Content-Type": "application/json"})

    # ---- lo que hace un test

    def orden(self, pago: Payment | str) -> dict[str, Any]:
        referencia = pago if isinstance(pago, str) else pago.reference
        return self.ordenes[referencia]

    def pagar(self, pago: Payment | str, estado: str = "paid", **cambios: Any) -> str:
        """El comprador termino en el procesador: la orden queda en `estado`.
        Si la orden no existe (una referencia ajena), se crea. Devuelve el `order_id`."""
        referencia = pago if isinstance(pago, str) else pago.reference
        orden = self.ordenes.setdefault(
            referencia,
            {
                "amount": pago.amount_cents if isinstance(pago, Payment) else 3200,
                "paid_order_status": "pending",
                "product_id": "mensual",
                "product_name": "Acceso Mensual",
            },
        )
        orden["paid_order_status"] = estado
        orden.update(cambios)
        return referencia

    def aprobar(self, pago: Payment) -> bytes:
        """El comprador pago con exito: la orden queda `paid` y sale su aviso."""
        self.pagar(pago, "paid")
        return self.aviso(pago, "ok")

    def aviso(
        self,
        pago: Payment | str,
        paid_status: str | None = None,
        *,
        firma: str | None = None,
        amount: str | None = None,
    ) -> bytes:
        """El cuerpo del aviso de pago (manual §9), firmado. `amount` es el
        texto del numero tal como va en el JSON; por defecto, el de la orden."""
        referencia = pago if isinstance(pago, str) else pago.reference
        orden = self.ordenes.get(referencia, {"amount": 3200, "paid_order_status": "paid"})
        estado = paid_status or ("ok" if orden["paid_order_status"] == "paid" else "ko")
        monto = amount or monto_js(orden["amount"])
        firmado = firma or firma_de_aviso(estado, referencia, monto)
        return (
            f'{{"paid_status":{json.dumps(estado)},"order_id":{json.dumps(referencia)},'
            f'"amount":{monto},"nt_signature":{json.dumps(firmado)}}}'
        ).encode()
