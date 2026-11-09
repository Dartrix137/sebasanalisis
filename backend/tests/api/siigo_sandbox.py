"""Siigo simulado sobre un `httpx.MockTransport`, para los tests de la factura.

El emisor que corre es el de verdad (`invoicing/siigo.SiigoIssuer`): solo el
transporte es de mentira, asi que cada peticion pasa por su codigo (token,
Partner-Id, Idempotency-Key, errores). Las respuestas imitan las documentadas
(`TokenOut`, `InvoiceOutDian`, `{"Status", "Errors"}`) y lo que se vio en la
empresa de pruebas el 2026-11-09 (token Bearer de 86400 s, 429 con la espera
en el mensaje).

Ningun test sale a la red.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import httpx

from app.billing.exchange_rates import ECB_SOURCE, TRM_SOURCE, RatePeriod
from app.invoicing.siigo import SiigoIssuer

DOCUMENTO = 27860
VENDEDOR = 916
FORMA_DE_PAGO = 11143
PRODUCTO = "SUSCRIPCION"
PARTNER = "sebasanalisisp"


@dataclass
class Falla:
    """Una respuesta de error programada para la proxima peticion que coincida."""

    status: int
    codes: list[str] = field(default_factory=list)
    message: str = "Error"
    timeout: bool = False


class SiigoSandbox:
    def __init__(self) -> None:
        self.pedidos: list[httpx.Request] = []
        self.clientes: dict[str, dict[str, Any]] = {}
        self.facturas: dict[str, dict[str, Any]] = {}
        self.por_llave: dict[str, str] = {}
        self.tokens = 0
        self.token_valido: str | None = None
        #: Fallas programadas por (metodo, ruta que empieza por), en orden.
        self.fallas: list[tuple[str, str, Falla]] = []
        #: Estado ante la DIAN con que nacen las facturas.
        self.estado_nuevo = "Accepted"
        #: Estado que devuelve una consulta posterior (`None`: el mismo).
        self.estado_al_consultar: str | None = None
        self.total_distinto: Decimal | None = None
        self.tipo_de_comprobante = {
            "id": DOCUMENTO, "code": "4", "name": "Factura electrónica de venta",
            "type": "FV", "active": True, "electronic_type": "ElectronicInvoice",
        }
        self.dormido: list[float] = []
        self.issuer = SiigoIssuer(
            username="usuario@prueba",
            access_key="clave-de-prueba",
            partner_id=PARTNER,
            document_type_id=DOCUMENTO,
            seller_id=VENDEDOR,
            payment_type_id=FORMA_DE_PAGO,
            product_code=PRODUCTO,
            min_interval_seconds=0,
            transport=httpx.MockTransport(self),
            sleep=self.dormido.append,
        )

    # ---------- Ayudas para los tests ----------

    def fallar(self, metodo: str, ruta: str, falla: Falla) -> None:
        self.fallas.append((metodo, ruta, falla))

    def pedidos_a(self, metodo: str, ruta: str) -> list[httpx.Request]:
        return [p for p in self.pedidos if p.method == metodo and p.url.path.startswith(ruta)]

    def cuerpo(self, pedido: httpx.Request) -> dict[str, Any]:
        return json.loads(pedido.content)

    # ---------- El transporte ----------

    def _error(self, falla: Falla) -> httpx.Response:
        return httpx.Response(
            falla.status,
            json={
                "Status": falla.status,
                "Errors": [
                    {"Code": c, "Message": falla.message, "Params": [], "Detail": "doc"}
                    for c in (falla.codes or ["error"])
                ],
            },
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.pedidos.append(request)
        path = request.url.path
        for i, (metodo, ruta, falla) in enumerate(self.fallas):
            if request.method == metodo and path.startswith(ruta):
                del self.fallas[i]
                if falla.timeout:
                    # La peticion llego y Siigo la proceso, pero la respuesta no.
                    if path == "/v1/invoices":
                        self._crear_factura(request)
                    raise httpx.ReadTimeout("tiempo agotado", request=request)
                return self._error(falla)

        if path == "/auth":
            self.tokens += 1
            self.token_valido = f"token-{self.tokens}"
            return httpx.Response(
                201,
                json={"access_token": self.token_valido, "expires_in": 86400,
                      "token_type": "Bearer", "scope": "SiigoAPI"},
            )
        if request.headers.get("Partner-Id") != PARTNER:
            return self._error(Falla(400, ["invalid_partner_id"]))
        if request.headers.get("Authorization") != f"Bearer {self.token_valido}":
            return self._error(Falla(401, ["unauthorized"]))

        if path == "/v1/document-types":
            return httpx.Response(200, json=[self.tipo_de_comprobante])
        if path == "/v1/payment-types":
            return httpx.Response(200, json=[{"id": FORMA_DE_PAGO, "name": "Cuenta por cobrar API",
                                              "type": "Cartera", "active": True, "due_date": False}])
        if path == "/v1/users":
            return httpx.Response(200, json={"pagination": {"page": 1}, "results": [
                {"id": VENDEDOR, "first_name": "Pruebas Api", "active": True}]})
        if path == "/v1/customers" and request.method == "GET":
            ident = request.url.params.get("identification", "")
            found = [self.clientes[ident]] if ident in self.clientes else []
            return httpx.Response(200, json={"pagination": {"page": 1}, "results": found})
        if path == "/v1/customers" and request.method == "POST":
            body = self.cuerpo(request)
            if body["identification"] in self.clientes:
                return self._error(Falla(400, ["already_exists"]))
            self.clientes[body["identification"]] = {**body, "id": str(uuid.uuid4())}
            return httpx.Response(201, json=self.clientes[body["identification"]])
        if path == "/v1/invoices" and request.method == "POST":
            return httpx.Response(201, json=self._crear_factura(request))
        if path.startswith("/v1/invoices/") and path.endswith("/stamp/errors"):
            fid = path.split("/")[3]
            return httpx.Response(200, json={"id": fid, "errors": [
                {"message": "Regla FAD06: el NIT del emisor no coincide"}]})
        if path.startswith("/v1/invoices/") and request.method == "GET":
            factura = self.facturas.get(path.split("/")[3])
            if factura is None:
                return httpx.Response(404)
            if self.estado_al_consultar:
                factura["stamp"]["status"] = self.estado_al_consultar
                if self.estado_al_consultar == "Accepted":
                    factura["stamp"]["cufe"] = "cufe-" + factura["id"]
            return httpx.Response(200, json=factura)
        return httpx.Response(404)

    def _crear_factura(self, request: httpx.Request) -> dict[str, Any]:
        llave = request.headers.get("Idempotency-Key", "")
        if llave in self.por_llave:
            return self.facturas[self.por_llave[llave]]
        body = self.cuerpo(request)
        if body["customer"]["identification"] not in self.clientes:
            raise AssertionError("La factura se mando antes de crear el tercero")
        fid = str(uuid.uuid4())
        numero = len(self.facturas) + 1
        total = self.total_distinto or Decimal(str(body["payments"][0]["value"]))
        aceptada = self.estado_nuevo == "Accepted"
        factura = {
            "id": fid, "name": f"FV-4-{numero}", "number": numero, "date": body["date"],
            "total": float(total),
            "stamp": {"status": self.estado_nuevo, "cufe": f"cufe-{fid}" if aceptada else None,
                      "observations": "", "errors": ""},
            "mail": {"status": "sent", "observations": ""},
            "cuerpo": body,
        }
        self.facturas[fid] = factura
        self.por_llave[llave] = fid
        return factura


class TasasSimuladas:
    """Las fuentes de tasas, sin red: la TRM y la del BCE de cualquier dia."""

    def __init__(self, trm: str = "3228.26", eur_usd: str = "1.1165",
                 publicadas: bool = True) -> None:
        self.trm = Decimal(trm)
        self.eur_usd = Decimal(eur_usd)
        self.publicadas = publicadas
        self.dias: list[date] = []

    def trm_covering(self, day: date) -> list[RatePeriod]:
        self.dias.append(day)
        if not self.publicadas:
            return []
        return [RatePeriod("USD/COP", day, day, self.trm, TRM_SOURCE)]

    def ecb_recent(self) -> list[RatePeriod]:
        dia = self.dias[-1] if self.dias else date.today()
        return [RatePeriod("EUR/USD", dia, dia, self.eur_usd, ECB_SOURCE)]
