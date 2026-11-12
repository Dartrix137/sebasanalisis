"""Emisor de facturas electronicas con la API de Siigo (docs/PLATAFORMA_COMPLETA.md
§3.17, "Paso 5.4"; Fase 5, paso 5.4).

Todo sale de la documentacion oficial de Siigo, leida el 2026-11-05 y el
2026-11-06, y probada contra su empresa de pruebas el 2026-11-09:

- Portal: `https://developers.siigo.com/docs/siigoapi/` (autenticacion,
  Partner-Id, idempotencia, manejo de errores, codigos HTTP, bloqueo de
  usuarios, crear factura, crear cliente).
- Referencia (API Blueprint): `https://jsapi.apiary.io/apis/siigoapi.apib`
  (`TokenIn`/`TokenOut`, `CustomerIn`, `InvoiceInDian`/`InvoiceOutDian`,
  `ItemIn`, `PaymentIn`, `StampOutDian`, consulta y errores de una factura).

Lo que importa aqui:

- `POST /auth` con `{username, access_key}` devuelve `access_token` (Bearer) y
  `expires_in` en segundos (86400: probado). Va en `Authorization: Bearer ...`
  (probado: con el prefijo responde 200). Se guarda en memoria y se renueva
  antes de vencer, o una vez ante un 401. Nunca va a un log.
- `Partner-Id`, en todas las peticiones: el nombre registrado de la aplicacion
  (`SIIGO_PARTNER_ID`). Un valor falso bloquea al usuario.
- Limite: 100 peticiones por minuto por empresa (10 en la de pruebas, y alli no
  admite rafagas: probado). Un 429 trae la espera en el mensaje ("Try again in
  16 seconds"). Se espera entre peticiones (`SIIGO_MIN_INTERVAL_SECONDS`) y,
  ante un 429 de espera corta, se espera y se reintenta una vez.
- Bloqueo: si en 7 dias mas del 80 % de las peticiones dan error, Siigo
  bloquea al usuario. Por eso un error de datos no se reintenta solo y uno de
  configuracion frena la corrida (`billing/invoice_document.classify`).
- `Idempotency-Key` en `POST /v1/invoices`: con la misma llave, si la factura
  ya existe, Siigo devuelve la ya creada. Timeout recomendado: 120 s o mas.
  Soporte (2026-11-09): hasta 30 caracteres, y "No existe tiempo limite de
  guardado, al ser usado, aunque se borre el documento permanecera usado".
- La factura exige que el tercero exista (`customer.identification`); se busca
  con `GET /v1/customers?identification=` y, si no esta, se crea con
  `POST /v1/customers`. `CustomerIn` marca `phones` como obligatorio, pero el
  portal lo da como opcional y soporte de Siigo lo confirmo (2026-11-09:
  "El telefono es un campo opcional"). No pedimos telefono: en la empresa de
  pruebas Siigo creo el tercero sin el, y le puso uno en ceros.
- `check_digit` no se manda: Siigo lo calcula solo. El PDF de Siigo rotula el
  documento de una persona como "NIT", con ese digito, aunque sea una cedula.
  Soporte (2026-11-09): "Es solo visual en el PDF, en el XML si se refleja con
  el codigo 13", y no se puede hacer que el PDF diga CC.
- Errores: `{"Status": 400, "Errors": [{"Code", "Message", "Params", "Detail"}]}`.
- Estados de una factura, segun soporte de Siigo (2026-11-09). Ante la DIAN
  (`stamp.status`): Draft, Sending, Rejected y Accepted. Del correo
  (`mail.status`): "Proccess of Sending, Send, Not Send, y Read"; la API los
  devolvio como `process_of_sending` y `not_sent`. Solo Accepted y Rejected
  son finales: con cualquier otro, la factura espera y se vuelve a consultar.
- El IVA del 0 % de la operacion excluida: soporte de Siigo (2026-11-09),
  "Para que se refleje el IVA del 0% deben informar el campo taxes con el ID
  del impuesto". En la factura, `items[].taxes[].id` es opcional y sale de
  `GET /v1/taxes`, cuyos impuestos traen `id`, `name`, `type` (`IVA`, ...),
  `percentage` y `active` (Apiary, `Tax`). Con `SIIGO_TAX_ID` el item lleva
  ese impuesto, y `check_ready` exige que sea de IVA, activo y del 0 %; sin
  el, el item va sin impuestos. El total no cambia.
- La empresa de pruebas no tiene habilitado el envio a la DIAN (soporte,
  2026-11-09): alli toda factura termina Rejected. La aceptacion solo se ve
  con la cuenta de la empresa.
- Notas credito (leido el 2026-11-11: portal, "Crear nota credito",
  `developers.siigo.com/docs/siigoapi/credit-note/1-create-credit-note/`, y
  en Apiary `CreditNoteIn`, `CreditNoteOut`, `StampOutDianNC`, `DocumentNC`):
  `POST /v1/credit-notes` con `document.id` (un tipo de comprobante de
  `GET /v1/document-types?type=NC`), `date` (en una electronica, no anterior a
  hoy), `invoice` (el UUID de la factura en Siigo; obligatorio si la nota es
  electronica), `reason` (obligatorio en un documento electronico), `items`,
  `payments` (`id` de `GET /v1/payment-types?document_type=NC`), `stamp` y
  `mail` (objetos `{send}`), con `Idempotency-Key` como la factura. Responde
  201 con `id`, `name` ("NC-2-22"), `total` y `stamp` con `status` y `cude`.
  Se consulta con `GET /v1/credit-notes/{id}`. No hay endpoint de errores de
  la DIAN para una nota (solo para facturas). La factura tiene que estar
  "enviada" a la DIAN (`invalid_document`). `reason` va como numero: el
  esquema lo da numerico, aunque el ejemplo del portal lo manda como texto.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.billing.invoice_document import CONFIG_CODES, classify
from app.core.config import Settings
from app.invoicing.base import (
    Buyer,
    CreditNoteDraft,
    InvoiceDraft,
    IssuedInvoice,
    IssuerConfigError,
    IssuerError,
    IssuerMisconfigured,
    IssuerRejected,
    IssuerTransient,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://api.siigo.com"
#: El tiempo de espera que recomienda Siigo al crear documentos.
_TIMEOUT = httpx.Timeout(120.0, connect=15.0)
#: Un 429 con una espera mas larga no se espera aqui: se deja para otra corrida.
MAX_INLINE_WAIT_SECONDS = 30.0
#: Margen para renovar el token antes de que venza.
_TOKEN_MARGIN_SECONDS = 600
#: La comprobacion de la configuracion se repite cada tanto (la cuenta cambia).
_READY_TTL_SECONDS = 6 * 3600
_PARTNER_ID = re.compile(r"^[A-Za-z0-9]{3,100}$")
_RETRY_IN = re.compile(r"in (\d+(?:\.\d+)?) seconds?", re.IGNORECASE)


def _number(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


CUSTOMER_MISMATCH = "customer_mismatch"
CUSTOMER_MISMATCH_MESSAGE = (
    "El cliente de Siigo con el documento de este comprador tiene otro tipo de documento,"
    " nombre o correo. Revísalo en Siigo Nube y reintenta la emisión."
)


def _plain(text: str) -> str:
    """Para comparar nombres y correos: sin tildes, sin mayusculas, sin espacios de mas."""
    decomposed = unicodedata.normalize("NFKD", text)
    return " ".join(
        "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold().split()
    )


def _same_buyer(customer: dict[str, Any], buyer: Buyer) -> bool:
    """El tercero de Siigo es este comprador: mismo tipo de documento, mismo nombre
    y su correo entre los contactos (a donde Siigo manda la factura).

    Al listar terceros, Siigo devuelve `id_type` como objeto `{code, name}` y
    `name` como lista (CustomerOut en la referencia de la API, leida el 2026-11-12).
    """
    raw_type = customer.get("id_type")
    id_type = raw_type.get("code") if isinstance(raw_type, dict) else raw_type
    names = customer.get("name") or []
    contacts = customer.get("contacts") or []
    emails = {
        _plain(str(c.get("email") or "")) for c in contacts if isinstance(c, dict)
    }
    return (
        str(id_type) == buyer.id_type
        and isinstance(names, list)
        and _plain(" ".join(str(n) for n in names))
        == _plain(f"{buyer.first_names} {buyer.last_names}")
        and _plain(buyer.email) in emails
    )


def _results(body: Any) -> list[dict[str, Any]]:
    """Las listas de Siigo vienen como `{pagination, results}` o como lista."""
    if isinstance(body, dict):
        body = body.get("results", [])
    return [r for r in body if isinstance(r, dict)] if isinstance(body, list) else []


def _invoice(body: Any) -> IssuedInvoice:
    if not isinstance(body, dict) or not body.get("id"):
        raise IssuerTransient("Siigo respondio un documento sin id", uncertain=True)
    stamp = body.get("stamp") if isinstance(body.get("stamp"), dict) else {}
    mail = body.get("mail") if isinstance(body.get("mail"), dict) else {}
    return IssuedInvoice(
        provider_id=str(body["id"]),
        name=str(body["name"]) if body.get("name") else None,
        total=_number(body.get("total")),
        stamp_status=str(stamp.get("status")) if stamp.get("status") else None,
        # Una nota credito trae `cude` (`StampOutDianNC`); el ejemplo del
        # portal trae los dos.
        cufe=str(stamp.get("cufe") or stamp.get("cude"))
        if stamp.get("cufe") or stamp.get("cude")
        else None,
        mail_status=str(mail.get("status")) if mail.get("status") else None,
    )


def _json_body(payload: dict[str, Any]) -> bytes:
    # Los montos van como numero: Decimal -> float con 2 decimales es exacto en
    # la representacion JSON (115339.27).
    return json.dumps(
        payload, ensure_ascii=False, default=lambda v: float(v) if isinstance(v, Decimal) else v
    ).encode()


class SiigoIssuer:
    name = "siigo"
    enabled = True

    def __init__(
        self,
        *,
        username: str,
        access_key: str,
        partner_id: str,
        document_type_id: int,
        seller_id: int,
        payment_type_id: int,
        product_code: str,
        cost_center_id: int = 0,
        tax_id: int = 0,
        credit_note_document_type_id: int = 0,
        base_url: str = BASE_URL,
        min_interval_seconds: float = 1.0,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._username = username
        self._access_key = access_key
        self._partner_id = partner_id
        self.document_type_id = document_type_id
        self.seller_id = seller_id
        self.payment_type_id = payment_type_id
        self.product_code = product_code
        self.cost_center_id = cost_center_id
        self.tax_id = tax_id
        self.credit_note_document_type_id = credit_note_document_type_id
        self.base_url = base_url.rstrip("/")
        self._min_interval = min_interval_seconds
        self._clock = clock
        self._sleep = sleep
        self._client = httpx.Client(base_url=self.base_url, timeout=_TIMEOUT, transport=transport)
        self._lock = threading.Lock()
        self._token: str | None = None
        self._token_expires = 0.0
        self._last_request = -1e9
        self._ready_until = 0.0

    def describe(self) -> str:
        return f"Siigo ({self.base_url})"

    # ---------- HTTP ----------

    def _pace(self) -> None:
        wait = self._last_request + self._min_interval - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._last_request = self._clock()

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        self._pace()
        try:
            return self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise IssuerTransient(
                f"Siigo no respondio a tiempo ({method} {path})", uncertain=method == "POST"
            ) from exc
        except httpx.HTTPError as exc:
            raise IssuerTransient(f"Siigo: {type(exc).__name__} ({method} {path})") from exc

    def _authenticate(self) -> str:
        response = self._send(
            "POST",
            "/auth",
            content=_json_body({"username": self._username, "access_key": self._access_key}),
            headers={"Partner-Id": self._partner_id, "Content-Type": "application/json"},
        )
        if response.status_code in (401, 403):
            raise IssuerMisconfigured("Siigo rechazo las credenciales (SIIGO_USERNAME/ACCESS_KEY)")
        if response.status_code not in (200, 201):
            self._raise_for(response, "POST /auth")
        body = response.json()
        token = body.get("access_token") if isinstance(body, dict) else None
        if not token:
            raise IssuerTransient("Siigo respondio el token sin access_token")
        expires = body.get("expires_in")
        lifetime = float(expires) if isinstance(expires, int | float) else 3600.0
        self._token = str(token)
        self._token_expires = self._clock() + max(lifetime - _TOKEN_MARGIN_SECONDS, 60.0)
        return self._token

    def _bearer(self) -> str:
        if self._token is None or self._clock() >= self._token_expires:
            return self._authenticate()
        return self._token

    def _raise_for(self, response: httpx.Response, what: str) -> None:
        codes: list[str] = []
        messages: list[str] = []
        try:
            body = response.json()
        except ValueError:
            body = None
        errors = body.get("Errors") if isinstance(body, dict) else None
        for item in errors if isinstance(errors, list) else []:
            if isinstance(item, dict):
                if item.get("Code"):
                    codes.append(str(item["Code"]))
                if item.get("Message"):
                    messages.append(str(item["Message"]))
        # El mensaje puede nombrar datos del comprador: al log van solo los codigos.
        logger.warning("Siigo respondio %s a %s: %s", response.status_code, what, codes or "-")
        text = "; ".join(messages)[:500] or f"HTTP {response.status_code}"
        kind = classify(response.status_code, codes)
        if kind == "transient":
            match = _RETRY_IN.search(" ".join(messages))
            raise IssuerTransient(
                text, codes, retry_after=float(match.group(1)) if match else None
            )
        if kind == "config":
            raise IssuerMisconfigured(text, codes)
        raise IssuerRejected(text, codes)

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        """Una peticion con el token. Renueva el token una vez ante un 401 y
        espera una vez ante un 429 corto. Devuelve el JSON."""
        renewed = waited = False
        while True:
            with self._lock:
                headers = {
                    "Authorization": f"Bearer {self._bearer()}",
                    "Partner-Id": self._partner_id,
                }
                if payload is not None:
                    headers["Content-Type"] = "application/json"
                if idempotency_key is not None:
                    headers["Idempotency-Key"] = idempotency_key
                response = self._send(
                    method,
                    path,
                    content=_json_body(payload) if payload is not None else None,
                    params=params,
                    headers=headers,
                )
            if response.status_code == 401 and not renewed:
                renewed = True
                self._token = None
                continue
            if response.status_code == 429 and not waited:
                match = _RETRY_IN.search(response.text)
                wait = float(match.group(1)) + 1 if match else None
                if wait is not None and wait <= MAX_INLINE_WAIT_SECONDS:
                    waited = True
                    self._sleep(wait)
                    continue
            if response.status_code >= 400:
                self._raise_for(response, f"{method} {path}")
            if response.status_code == 204 or not response.content:
                return None
            try:
                return response.json()
            except ValueError as exc:
                raise IssuerTransient(f"Siigo respondio algo que no es JSON ({path})") from exc

    # ---------- Configuracion ----------

    def check_ready(self) -> None:
        """Que el tipo de comprobante sea de factura electronica y este activo,
        y que existan la forma de pago y el vendedor. Se comprueba antes de
        emitir, no al arrancar: si Siigo esta caido, la API tiene que arrancar
        igual (el pago no depende de la factura)."""
        if self._clock() < self._ready_until:
            return
        types = _results(self._request("GET", "/v1/document-types", params={"type": "FV"}))
        document = next((t for t in types if t.get("id") == self.document_type_id), None)
        if document is None or not document.get("active"):
            raise IssuerMisconfigured(
                f"SIIGO_DOCUMENT_TYPE_ID={self.document_type_id} no es un tipo de factura activo"
            )
        if document.get("cost_center") and not self.cost_center_id:
            # Sin el, Siigo responde `documents_service` ("could not be
            # completed with the data you submitted"): probado el 2026-11-09.
            raise IssuerMisconfigured(
                f"SIIGO_DOCUMENT_TYPE_ID={self.document_type_id} pide centro de costo:"
                " falta SIIGO_COST_CENTER_ID"
            )
        if document.get("electronic_type") != "ElectronicInvoice":
            raise IssuerMisconfigured(
                f"SIIGO_DOCUMENT_TYPE_ID={self.document_type_id} no es de factura electronica"
                f" ({document.get('electronic_type')})"
            )
        payments = _results(
            self._request("GET", "/v1/payment-types", params={"document_type": "FV"})
        )
        if not any(p.get("id") == self.payment_type_id and p.get("active") for p in payments):
            raise IssuerMisconfigured(
                f"SIIGO_PAYMENT_TYPE_ID={self.payment_type_id} no es una forma de pago activa"
            )
        users = _results(self._request("GET", "/v1/users"))
        if not any(u.get("id") == self.seller_id and u.get("active") for u in users):
            raise IssuerMisconfigured(f"SIIGO_SELLER_ID={self.seller_id} no es un usuario activo")
        if self.tax_id:
            taxes = _results(self._request("GET", "/v1/taxes"))
            tax = next((t for t in taxes if t.get("id") == self.tax_id), None)
            if (
                tax is None
                or not tax.get("active")
                or tax.get("type") != "IVA"
                or _number(tax.get("percentage")) != 0
            ):
                raise IssuerMisconfigured(
                    f"SIIGO_TAX_ID={self.tax_id} no es un impuesto de IVA del 0 % activo"
                )
        if self.credit_note_document_type_id:
            self._check_credit_note_type()
        self._ready_until = self._clock() + _READY_TTL_SECONDS

    def _check_credit_note_type(self) -> None:
        """El tipo de comprobante de nota credito, activo, y la forma de pago
        habilitada para notas credito. `DocumentTypeNC` no trae
        `electronic_type`: que sea electronica lo dice la configuracion en
        Siigo Nube."""
        types = _results(self._request("GET", "/v1/document-types", params={"type": "NC"}))
        document = next((t for t in types if t.get("id") == self.credit_note_document_type_id), None)
        if document is None or not document.get("active"):
            raise IssuerMisconfigured(
                f"SIIGO_CREDIT_NOTE_DOCUMENT_TYPE_ID={self.credit_note_document_type_id}"
                " no es un tipo de nota credito activo"
            )
        if document.get("cost_center") and not self.cost_center_id:
            raise IssuerMisconfigured(
                f"SIIGO_CREDIT_NOTE_DOCUMENT_TYPE_ID={self.credit_note_document_type_id} pide"
                " centro de costo: falta SIIGO_COST_CENTER_ID"
            )
        payments = _results(
            self._request("GET", "/v1/payment-types", params={"document_type": "NC"})
        )
        if not any(p.get("id") == self.payment_type_id and p.get("active") for p in payments):
            raise IssuerMisconfigured(
                f"SIIGO_PAYMENT_TYPE_ID={self.payment_type_id} no es una forma de pago activa"
                " para notas credito"
            )

    # ---------- Terceros ----------

    def _existing_customer(self, buyer: Buyer) -> dict[str, Any] | None:
        found = _results(
            self._request("GET", "/v1/customers", params={"identification": buyer.id_number})
        )
        return next((c for c in found if str(c.get("identification")) == buyer.id_number), None)

    def _create_customer(self, buyer: Buyer) -> None:
        payload = {
            "type": "Customer",
            "person_type": "Person",
            "id_type": buyer.id_type,
            "identification": buyer.id_number,
            "name": [buyer.first_names, buyer.last_names],
            "vat_responsible": False,
            "fiscal_responsibilities": [{"code": "R-99-PN"}],
            "address": {
                "address": buyer.address,
                "city": {
                    "country_code": buyer.country_code,
                    "state_code": buyer.state_code,
                    "city_code": buyer.city_code,
                },
            },
            "contacts": [
                {
                    "first_name": buyer.first_names,
                    "last_name": buyer.last_names,
                    "email": buyer.email,
                }
            ],
        }
        try:
            self._request("POST", "/v1/customers", payload=payload)
        except IssuerRejected as exc:
            # Otra emision lo creo entre la busqueda y la creacion.
            if "already_exists" not in exc.codes:
                raise
        except IssuerMisconfigured as exc:
            # Al crear el tercero, `invalid_reference` es de los datos de ese
            # comprador, no de la cuenta: es lo que responde Siigo a una ciudad
            # que no reconoce (probado en la empresa de pruebas el 2026-11-10:
            # Us/32/3298 rechazada con 400 `invalid_reference`, la 3299 creada en
            # Siigo Nube aceptada). Lo demas del tercero es fijo. Como error de
            # configuracion frenaria la emision de todas las facturas por los
            # datos de una; asi queda fallida solo la suya (§3.17).
            if set(exc.codes) & CONFIG_CODES == {"invalid_reference"}:
                raise IssuerRejected(str(exc), exc.codes) from exc
            raise

    # ---------- Facturas ----------

    def issue(self, draft: InvoiceDraft) -> IssuedInvoice:
        customer = self._existing_customer(draft.buyer)
        if customer is None:
            self._create_customer(draft.buyer)
        elif not _same_buyer(customer, draft.buyer):
            # Siigo identifica al tercero solo por el numero de documento. Si el
            # que ya existe es de otra persona (otra cuenta escribio ese numero, o
            # el comprador cambio su nombre o correo), la factura saldria a su
            # nombre y Siigo la mandaria a su correo. Se aparta para el admin
            # (auditoria del 2026-11-12, decidido por el usuario). Ni el mensaje
            # ni el log llevan el documento.
            raise IssuerRejected(CUSTOMER_MISMATCH_MESSAGE, [CUSTOMER_MISMATCH])
        item: dict[str, Any] = {
            "code": self.product_code,
            "description": draft.description,
            "quantity": 1,
            "price": draft.amount,
        }
        if self.tax_id:
            item["taxes"] = [{"id": self.tax_id}]
        payload: dict[str, Any] = {
            "document": {"id": self.document_type_id},
            "date": draft.issue_date.isoformat(),
            "customer": {"identification": draft.buyer.id_number, "branch_office": 0},
            "seller": self.seller_id,
            "stamp": {"send": True},
            "mail": {"send": True},
            "observations": draft.observations,
            "items": [item],
            "payments": [{"id": self.payment_type_id, "value": draft.amount}],
        }
        if self.cost_center_id:
            payload["cost_center"] = self.cost_center_id
        body = self._request(
            "POST", "/v1/invoices", payload=payload, idempotency_key=draft.idempotency_key
        )
        return _invoice(body)

    def fetch(self, provider_id: str) -> IssuedInvoice:
        return _invoice(self._request("GET", f"/v1/invoices/{provider_id}"))

    def stamp_errors(self, provider_id: str) -> list[str]:
        body = self._request("GET", f"/v1/invoices/{provider_id}/stamp/errors")
        errors = body.get("errors") if isinstance(body, dict) else None
        return [
            str(e["message"])
            for e in (errors if isinstance(errors, list) else [])
            if isinstance(e, dict) and e.get("message")
        ]


    # ---------- Notas credito ----------

    @property
    def credit_notes_enabled(self) -> bool:
        return bool(self.credit_note_document_type_id)

    def issue_credit_note(self, draft: CreditNoteDraft) -> IssuedInvoice:
        if not self.credit_note_document_type_id:
            raise IssuerMisconfigured("Falta SIIGO_CREDIT_NOTE_DOCUMENT_TYPE_ID")
        item: dict[str, Any] = {
            "code": self.product_code,
            "description": draft.description,
            "quantity": 1,
            "price": draft.amount,
        }
        if self.tax_id:
            item["taxes"] = [{"id": self.tax_id}]
        payload: dict[str, Any] = {
            "document": {"id": self.credit_note_document_type_id},
            "date": draft.issue_date.isoformat(),
            "invoice": draft.invoice_provider_id,
            "reason": draft.reason,
            "stamp": {"send": True},
            "mail": {"send": True},
            "observations": draft.observations,
            "items": [item],
            "payments": [{"id": self.payment_type_id, "value": draft.amount}],
        }
        if self.cost_center_id:
            payload["cost_center"] = self.cost_center_id
        body = self._request(
            "POST", "/v1/credit-notes", payload=payload, idempotency_key=draft.idempotency_key
        )
        return _invoice(body)

    def fetch_credit_note(self, provider_id: str) -> IssuedInvoice:
        return _invoice(self._request("GET", f"/v1/credit-notes/{provider_id}"))


_REQUIRED = (
    "siigo_username",
    "siigo_access_key",
    "siigo_partner_id",
    "siigo_document_type_id",
    "siigo_seller_id",
    "siigo_payment_type_id",
    "siigo_product_code",
)


def from_settings(settings: Settings, **kwargs: Any) -> SiigoIssuer:
    missing = [name.upper() for name in _REQUIRED if not getattr(settings, name)]
    if missing:
        raise IssuerConfigError(f"Con INVOICE_ISSUER=siigo faltan: {', '.join(missing)}")
    if not _PARTNER_ID.match(settings.siigo_partner_id):
        raise IssuerConfigError(
            "SIIGO_PARTNER_ID va de 3 a 100 letras o numeros, sin espacios ni simbolos"
        )
    if not settings.siigo_api_base_url.startswith("https://"):
        raise IssuerConfigError("SIIGO_API_BASE_URL tiene que ir por HTTPS")
    return SiigoIssuer(
        username=settings.siigo_username,
        access_key=settings.siigo_access_key,
        partner_id=settings.siigo_partner_id,
        document_type_id=settings.siigo_document_type_id,
        seller_id=settings.siigo_seller_id,
        payment_type_id=settings.siigo_payment_type_id,
        product_code=settings.siigo_product_code,
        cost_center_id=settings.siigo_cost_center_id,
        tax_id=settings.siigo_tax_id,
        credit_note_document_type_id=settings.siigo_credit_note_document_type_id,
        base_url=settings.siigo_api_base_url,
        min_interval_seconds=settings.siigo_min_interval_seconds,
        **kwargs,
    )


def emission_date_ok(issue_date: date, today: date) -> bool:
    """Siigo no admite una factura electronica con fecha anterior a hoy."""
    return issue_date >= today


__all__ = ["SiigoIssuer", "from_settings", "IssuerError"]
