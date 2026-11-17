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

Y las suscripciones (paso 5.3b, `tspay-subscriptions.md` del 2026-11-17), en
`SuscripcionesSandbox`: el catalogo, el alta y el cobro firmados sobre el JSON
canonico (con su propio calculo), la idempotencia por `idempotency_key`, el
`external_id` unico, la consulta de la suscripcion y de sus cobros, y los
avisos firmados. El listado de cobros y los estados de la suscripcion van
como se vieron en produccion el 2026-11-17.
"""

import hashlib
import hmac
import json
import uuid
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
        self.suscripciones = SuscripcionesSandbox()
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
        if path.startswith("/subscriptions"):
            respuesta = self.suscripciones.responder(request, path)
            if respuesta is not None:
                return respuesta
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


# ---------------------------------------------------------------- suscripciones (paso 5.3b)

#: El medio de las suscripciones del sandbox, como lo devolvio el 2026-11-17.
MEDIO_SUSCRIPCION: dict[str, Any] = {
    "key": "solidgate",
    "provider": "SOLIDGATE",
    "name": "Solidgate (suscripciones)",
    "currency": "EUR",
    "billing_mode": "MERCHANT_MANAGED",
    "countries": [],
    "priceMin": 1,
    "priceMax": 500000,
    "fields": ["email", "country", "language", "terms_accepted"],
    "periodicities": [
        "diaria", "semanal", "2_semanas", "mensual", "bimestral", "trimestral", "semestral", "anual",
    ],
    "capabilities": {
        "automatic_renewal": True,
        "merchant_initiated_charges": True,
        "payment_retries_configured": False,
    },
}

ALTA_OBLIGATORIOS = (
    "idempotency_key", "product_id", "product_name", "amount", "periodicity", "external_id",
    "email", "country", "language", "url_ok", "url_ko", "notification_url", "terms_accepted",
)
COBRO_OBLIGATORIOS = ("idempotency_key", "period_id", "payment_method_id", "amount")


def canonico(valor: Any) -> str:
    """`tspay-subscriptions.md` §2.4, su implementacion de referencia en Python,
    escrita aqui aparte de la de la aplicacion."""
    return json.dumps(valor, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def firma_canonica(texto: str) -> str:
    return hmac.new(SECRETO.encode(), texto.encode("utf-8"), hashlib.sha256).hexdigest()


class SuscripcionesSandbox:
    """Las suscripciones de Tipster Page, para `TipsterSandbox`."""

    def __init__(self) -> None:
        self.activas = True
        #: subscription_id -> la suscripcion.
        self.suscripciones: dict[str, dict[str, Any]] = {}
        #: payment_id -> el cobro.
        self.cobros: dict[str, dict[str, Any]] = {}
        #: Los cuerpos de las peticiones firmadas tal como llegaron.
        self.pedidos: list[tuple[str, dict[str, Any]]] = []
        self._claves: dict[str, tuple[str, str]] = {}
        #: Lo que respondera el proximo cobro: PAID, FAILED, PENDING, 3DS (pendiente
        #: de que el titular se autentique) o SIN_REINTENTO (rechazado con
        #: `retry_allowed: false`, como una tarjeta bloqueada).
        self.resultado_del_cobro = "PAID"
        #: Los enlaces de cambio de tarjeta abiertos: subscription_id -> accion.
        self.cambios_de_tarjeta: dict[str, str] = {}
        #: Forzar la respuesta del proximo cobro: (codigo, mensaje).
        self.respuesta_cobro: tuple[int, str] | None = None

    def responder(self, request: httpx.Request, path: str) -> httpx.Response | None:
        if request.method == "GET" and path == "/subscriptions/payment-methods":
            return httpx.Response(200, json=[MEDIO_SUSCRIPCION] if self.activas else [])
        if request.method == "POST" and path == "/subscriptions":
            return self._alta(request)
        partes = path.removeprefix("/subscriptions/").split("/")
        if not path.startswith("/subscriptions/") or partes[0] not in self.suscripciones:
            return None if not path.startswith("/subscriptions") else _no_encontrada()
        sid = partes[0]
        if request.method == "GET" and len(partes) == 1:
            return httpx.Response(200, json=self._vista(sid))
        if request.method == "GET" and partes[1:] == ["payments"]:
            items = [_como_en_el_listado(c) for c in self.cobros.values() if c["subscription_id"] == sid]
            return httpx.Response(200, json={"items": items, "next_cursor": None})
        if request.method == "GET" and len(partes) == 3 and partes[1] == "payments":
            cobro = self.cobros.get(partes[2])
            if cobro is None or cobro["subscription_id"] != sid:
                return _no_encontrada()
            return httpx.Response(200, json=cobro)
        if request.method == "POST" and partes[1:] == ["payments"]:
            return self._cobro(request, sid)
        if request.method == "POST" and partes[1:] in (["payment-method"], ["payment-recovery"]):
            return self._enlace_de_tarjeta(request, sid, partes[1])
        if request.method == "DELETE" and partes[1:] == ["payment-method"]:
            return self._borrar_tarjeta(request, sid)
        return None

    def _enlace_de_tarjeta(self, request: httpx.Request, sid: str, ruta: str) -> httpx.Response:
        accion = "RECOVERY" if ruta == "payment-recovery" else "PAYMENT_METHOD"
        body = self._firmado(request, accion, sid)
        if body is None:
            return _error("Invalid signature")
        if set(body) != {"idempotency_key"}:
            return _error("Invalid parameters")
        self.cambios_de_tarjeta[sid] = accion
        return httpx.Response(
            201,
            json={
                "checkout_url": f"https://checkout.solidgate.test/tarjeta/{sid}",
                "expires_at": "2026-11-19T19:00:00.000Z",
            },
        )

    def _borrar_tarjeta(self, request: httpx.Request, sid: str) -> httpx.Response:
        body = self._firmado(request, "DELETE_PAYMENT_METHOD", sid)
        if body is None:
            return _error("Invalid signature")
        suscripcion = self.suscripciones[sid]
        if body.get("scope") != "SUBSCRIPTION" or body.get("payment_method_id") != suscripcion["payment_method_id"]:
            return _error("Invalid parameters")
        suscripcion.update(
            status="CANCELLED",
            payment_method_deletion={
                "status": "CONFIRMED",
                "scope": "SUBSCRIPTION",
                "provider_revoked": False,
                "payment_method_id": suscripcion["payment_method_id"],
                "deleted_at": "2026-11-17T20:00:00.000Z",
            },
        )
        return httpx.Response(200, json=self._vista(sid))

    # ---- lo que hace la pasarela

    def _firmado(self, request: httpx.Request, action: str, resource: str) -> dict[str, Any] | None:
        body = json.loads(request.content)
        self.pedidos.append((action, body))
        firma = body.pop("tspay_signature", None)
        texto = canonico(
            {"merchant": MERCHANT, "action": action, "resource": resource, "parameters": body}
        )
        return body if firma == firma_canonica(texto) else None

    def _idempotente(self, body: dict[str, Any]) -> httpx.Response | None:
        """Suscripciones §2.6: misma clave y mismos parametros devuelve lo de
        antes; misma clave y otros parametros, 409."""
        anterior = self._claves.get(body["idempotency_key"])
        if anterior is None:
            return None
        if anterior[0] != canonico(body):
            return httpx.Response(
                409, json={"statusCode": 409, "message": "idempotency_key ya tiene otros parámetros"}
            )
        return httpx.Response(201, content=anterior[1].encode(), headers={"Content-Type": "application/json"})

    def _alta(self, request: httpx.Request) -> httpx.Response:
        body = self._firmado(request, "CREATE", "")
        if body is None:
            return _error("Invalid signature")
        if any(campo not in body for campo in ALTA_OBLIGATORIOS) or body["terms_accepted"] is not True:
            return _error("Invalid parameters")
        repetida = self._idempotente(body)
        if repetida is not None:
            return repetida
        if any(s["external_id"] == body["external_id"] for s in self.suscripciones.values()):
            return httpx.Response(409, json={"statusCode": 409, "message": "external_id ya existe"})
        if body["periodicity"] not in MEDIO_SUSCRIPCION["periodicities"]:
            return _error("Invalid periodicity")
        sid = str(uuid.uuid4())
        self.suscripciones[sid] = {
            "subscription_id": sid,
            "external_id": body["external_id"],
            "status": "PENDING_PAYMENT",
            "payment_status": "PENDING",
            "amount": body["amount"],
            "currency": "EUR",
            "periodicity": body["periodicity"],
            "billing_mode": "MERCHANT_MANAGED",
            "payment_method_id": None,
            "next_charge_at": None,
            "checkout_url": f"https://checkout.solidgate.test/{sid}",
            "_email": body["email"],
            "_tarjeta": None,
        }
        texto = json.dumps(self._vista(sid))
        self._claves[body["idempotency_key"]] = (canonico(body), texto)
        return httpx.Response(201, content=texto.encode(), headers={"Content-Type": "application/json"})

    def _cobro(self, request: httpx.Request, sid: str) -> httpx.Response:
        body = self._firmado(request, "CHARGE", sid)
        if body is None:
            return _error("Invalid signature")
        if any(campo not in body for campo in COBRO_OBLIGATORIOS) or body["period_id"] == "initial":
            return _error("Invalid parameters")
        repetida = self._idempotente(body)
        if repetida is not None:
            return repetida
        if self.respuesta_cobro is not None:
            codigo, mensaje = self.respuesta_cobro
            self.respuesta_cobro = None
            return httpx.Response(codigo, json={"statusCode": codigo, "message": mensaje})
        suscripcion = self.suscripciones[sid]
        if body["payment_method_id"] != suscripcion["payment_method_id"]:
            return _error("Payment method not available")
        if any(
            c["period_id"] == body["period_id"] and c["status"] == "PAID"
            for c in self.cobros.values()
            if c["subscription_id"] == sid
        ):
            return httpx.Response(409, json={"statusCode": 409, "message": "Periodo ya pagado"})
        estado = "FAILED" if suscripcion["_tarjeta"] == "falla_renovacion" else self.resultado_del_cobro
        cobro = self._anotar_cobro(sid, body["period_id"], body["amount"], estado)
        cobro["payment_method_id"] = body["payment_method_id"]
        texto = json.dumps(cobro)
        self._claves[body["idempotency_key"]] = (canonico(body), texto)
        return httpx.Response(201, content=texto.encode(), headers={"Content-Type": "application/json"})

    def _anotar_cobro(self, sid: str, period_id: str, amount: Any, estado: str) -> dict[str, Any]:
        pid = str(uuid.uuid4())
        sin_reintento = estado == "SIN_REINTENTO"
        tres_ds = estado == "3DS"
        cobro = {
            "payment_id": pid,
            "subscription_id": sid,
            "period_id": period_id,
            "payment_method_id": self.suscripciones[sid]["payment_method_id"],
            "amount": amount,
            "currency": "EUR",
            "status": "FAILED" if sin_reintento else ("PENDING" if tres_ds else estado),
            "error_code": "3.01" if sin_reintento else ("3.02" if estado == "FAILED" else None),
            "retry_allowed": False if sin_reintento else (True if estado == "FAILED" else None),
            "authentication_required": tres_ds,
            "authentication_url": f"https://3ds.solidgate.test/{pid}" if tres_ds else None,
        }
        self.cobros[pid] = cobro
        return cobro

    def _vista(self, sid: str) -> dict[str, Any]:
        return {k: v for k, v in self.suscripciones[sid].items() if not k.startswith("_")}

    # ---- lo que hace un test

    def de_pago(self, external_id: str) -> dict[str, Any]:
        return next(s for s in self.suscripciones.values() if s["external_id"] == external_id)

    def pagar_alta(self, external_id: str, tarjeta: str = "ok") -> dict[str, Any]:
        """El cliente termino en la pagina de Solidgate: `ok`, `falla_renovacion`
        (el alta va bien y las renovaciones se rechazan) o `rechazada` (el
        primer pago falla y la suscripcion queda `EXPIRED`, sin cobro)."""
        suscripcion = self.de_pago(external_id)
        if tarjeta == "rechazada":
            suscripcion["status"] = "EXPIRED"
            return suscripcion
        suscripcion.update(
            status="ACTIVE",
            payment_status="PAID",
            payment_method_id=str(uuid.uuid4()),
            _tarjeta=tarjeta,
        )
        self._anotar_cobro(suscripcion["subscription_id"], "initial", suscripcion["amount"], "PAID")
        return suscripcion

    def verificar(self, external_id: str, tarjeta: str = "ok") -> dict[str, Any]:
        """El cliente verifico la tarjeta por 0 en un alta `setup_only`: queda
        guardada, sin cobro (suscripciones §3.2)."""
        suscripcion = self.de_pago(external_id)
        suscripcion.update(
            status="ACTIVE",
            payment_status="VERIFIED",
            payment_method_id=str(uuid.uuid4()),
            _tarjeta=tarjeta,
        )
        return suscripcion

    def guardar_tarjeta(self, sid: str, tarjeta: str = "ok") -> dict[str, Any]:
        """El cliente guardo otra tarjeta con el enlace de cambio o de
        recuperacion: la suscripcion tiene otro `payment_method_id`."""
        assert sid in self.cambios_de_tarjeta, "no se abrio el enlace"
        del self.cambios_de_tarjeta[sid]
        suscripcion = self.suscripciones[sid]
        suscripcion.update(payment_method_id=str(uuid.uuid4()), _tarjeta=tarjeta)
        return suscripcion

    def aviso(self, suscripcion: dict[str, Any], event_type: str, data: dict[str, Any] | None = None,
              *, event_id: str | None = None, firma: str | None = None) -> bytes:
        """Un aviso de la suscripcion (§3.1), firmado sobre su JSON canonico sin
        `nt_signature` (§3.3), con las claves en el orden en que las manda."""
        cuerpo: dict[str, Any] = {
            "event_id": event_id or uuid.uuid4().hex,
            "event_type": event_type,
            "subscription_id": suscripcion["subscription_id"],
            "external_id": suscripcion["external_id"],
            "occurred_at": "2026-12-17T10:00:00.000Z",
            "data": data or {},
        }
        cuerpo["nt_signature"] = firma or firma_canonica(canonico(cuerpo))
        return json.dumps(cuerpo).encode()


def _como_en_el_listado(cobro: dict[str, Any]) -> dict[str, Any]:
    """Un cobro como lo trae `GET /subscriptions/{id}/payments`, visto en
    produccion el 2026-11-17: con `order_id` y `cycle`, sin `subscription_id`
    y con el estado en minusculas."""
    return {
        "payment_id": cobro["payment_id"],
        "order_id": f"{cobro['period_id']}:{cobro['payment_id']}",
        "cycle": 1 if cobro["period_id"] == "initial" else 2,
        "period_id": cobro["period_id"],
        "amount": cobro["amount"],
        "currency": cobro["currency"],
        "status": cobro["status"].lower(),
        "occurred_at": "2026-11-17T19:41:01.000Z",
    }


def _error(mensaje: str) -> httpx.Response:
    return httpx.Response(400, json={"statusCode": 400, "message": mensaje, "error": "Bad Request"})


def _no_encontrada() -> httpx.Response:
    return httpx.Response(404, json={"statusCode": 404, "message": "Suscripción no encontrada"})
