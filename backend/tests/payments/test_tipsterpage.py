"""`TipsterPageProvider` sin base de datos ni red (manual V2 de Tipster Page).

Los vectores de firma se calcularon aparte, con `openssl dgst -sha256 -hmac`,
sobre el ejemplo del manual §7.3 y §9: no salen del codigo que prueban.
"""

import json
import logging
from decimal import Decimal

import httpx
import pytest

from app.core.config import Settings
from app.payments.base import (
    CheckoutOrder,
    CheckoutRejected,
    PaymentProviderError,
    ProviderMisconfigured,
)
from app.payments.tipsterpage import (
    PRODUCTION_BASE_URL,
    SANDBOX_BASE_URL,
    TipsterPageProvider,
    check_startup,
    format_amount,
    from_settings,
    notification_signature,
    order_signature,
)

CLAVE = "clave-de-prueba"

# Manual §7.3: los parametros del ejemplo, con el nombre sin tilde.
EJEMPLO = {
    "order_id": "ORD-1001",
    "product_id": "PROD-50",
    "product_name": "Suscripcion Premium",
    "product_description": "Acceso 1 mes",
    "amount": "12.00",
    "payment_method": "cardtpv",
    "url_ok": "https://miweb.com/pago-ok",
    "url_ko": "https://miweb.com/pago-ko",
    "notification_url": "https://miweb.com/tspay/notify",
    "country": "ES",
}


# ---------- Firmas ----------


def test_la_firma_de_la_orden_con_un_vector_calculado_aparte() -> None:
    """§7.1: HMAC-SHA256 en hex sobre los diez valores concatenados, sin separador."""
    assert order_signature(CLAVE, EJEMPLO) == (
        "b33849fbf7d2d1e68c6b3a14043207f999558aec63bcd35121d0f6947fc51d32"
    )


# La orden de ejemplo que mando Tipster Page el 2026-11-05 (`orderexample.json`,
# con su script de referencia `sign-tspay-order.js`, en
# `docs/docs tipsterpage/`, fuera del repositorio). El monto va sin decimales y
# el pais en minusculas: se firman tal como se envian.
EJEMPLO_TIPSTER_PAGE = {
    "order_id": "8dca39a8-36ea-40ca-a28a-7cd0032f8b61-17399945368027",
    "product_id": "96",
    "product_name": "Gorgeous Wooden Bike EBANX ECUADOR",
    "product_description": "Suscripción a Gorgeous Wooden Bike EBANX ECUADOR",
    "amount": "3",
    "country": "es",
    "payment_method": "cardtpv",
    "url_ok": "https://molina.korvusinc.com/compra_ok.php",
    "url_ko": "https://molina.korvusinc.com/compra_error.php",
    "notification_url": "https://molina.korvusinc.com/notificacion.php",
}


def test_la_firma_coincide_con_el_script_de_referencia_de_tipster_page() -> None:
    """El vector sale de su script (`node sign-tspay-order.js --secret
    clave-de-prueba --signature-only`), no de este codigo. El JSON trae los
    campos en otro orden (`country` antes de `payment_method`): la firma sigue
    el orden fijo, no el del cuerpo. Lleva una tilde: se firma en UTF-8."""
    assert order_signature(CLAVE, EJEMPLO_TIPSTER_PAGE) == (
        "56a637d4a6411a344c626c8f247ea11403ebe2e34a586710e4e28f32ee246096"
    )


def test_un_campo_ausente_aporta_la_cadena_vacia() -> None:
    """§7.1: sin `notification_url` ni `country`."""
    sin = {k: v for k, v in EJEMPLO.items() if k not in ("notification_url", "country")}
    assert order_signature(CLAVE, sin) == (
        "8df6cc0403b93b94dfd1c5853e187423435d3765e2a84232d32950ad4872f72e"
    )


def test_los_datos_del_comprador_no_entran_en_la_firma() -> None:
    con_datos = {**EJEMPLO, "firstName": "Jose", "phone": "+34600000000"}
    assert order_signature(CLAVE, con_datos) == order_signature(CLAVE, EJEMPLO)


def test_la_firma_del_aviso_con_un_vector_calculado_aparte() -> None:
    """§9.1: sobre `paid_status + order_id + amount`, con el monto tal como llega."""
    assert notification_signature(CLAVE, "ok", "ORD-1001", "12.5") == (
        "e297b6513bd02bc0aa23d414dca7b255d5be71245923eb4c67b2718bb14191ca"
    )
    assert notification_signature(CLAVE, "ok", "ORD-1001", "12.50") == (
        "fdb8d6fe224c1a04654be6ddf5abf3c4005d506d2b9142671b087413030c4cc8"
    )


@pytest.mark.parametrize(
    ("centavos", "texto"), [(3200, "32.00"), (4600, "46.00"), (1250, "12.50"), (5, "0.05"), (100, "1.00")]
)
def test_el_monto_de_la_orden_va_con_dos_decimales(centavos: int, texto: str) -> None:
    assert format_amount(centavos) == texto


def test_un_monto_no_positivo_no_se_formatea() -> None:
    with pytest.raises(ValueError):
        format_amount(0)


# ---------- El proveedor sobre un transporte simulado ----------


class Respuestas:
    """Lo que responde la "pasarela" a cada ruta, y lo que le llego."""

    def __init__(self, **rutas: httpx.Response) -> None:
        self.rutas = rutas
        self.peticiones: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.peticiones.append(request)
        for prefijo, respuesta in self.rutas.items():
            if request.url.path.startswith("/tspayv2/" + prefijo.replace("_", "-")):
                return respuesta
        return httpx.Response(404, json={"message": "Not Found"})


def _proveedor(respuestas: Respuestas) -> TipsterPageProvider:
    return TipsterPageProvider(
        base_url=SANDBOX_BASE_URL,
        merchant_code="TSPAY-CLIENT-X",
        auth_bearer="token-x",
        secret_key=CLAVE,
        transport=httpx.MockTransport(respuestas),
    )


def _orden(**cambios) -> CheckoutOrder:
    datos = {
        "reference": "SA-abc",
        "amount_cents": 3200,
        "currency": "EUR",
        "product_code": "mensual",
        "product_name": "Acceso Mensual",
        "product_description": "Sebasanalisis: acceso por 1 mes",
        "method": "ebanxpsecolombia",
        "country": "CO",
        "url_ok": "https://app.test/pago/1",
        "url_ko": "https://app.test/pago/1",
        "notification_url": "https://api.test/webhooks/payments",
        "buyer": {"firstName": "Ana"},
    }
    datos.update(cambios)
    return CheckoutOrder(**datos)


def test_las_llamadas_llevan_las_dos_cabeceras() -> None:
    """§4: `X-TSPAY-USER` y `Authorization: Bearer`."""
    respuestas = Respuestas(payment_methods=httpx.Response(200, json=[]))
    _proveedor(respuestas).payment_methods("CO")
    [peticion] = respuestas.peticiones
    assert peticion.headers["X-TSPAY-USER"] == "TSPAY-CLIENT-X"
    assert peticion.headers["Authorization"] == "Bearer token-x"
    assert str(peticion.url) == f"{SANDBOX_BASE_URL}/payment-methods?country-code=CO"


def test_la_orden_va_firmada_con_los_datos_del_comprador_aparte() -> None:
    respuestas = Respuestas(
        create_order_tspay=httpx.Response(201, text="<html></html>", headers={"Content-Type": "text/html"})
    )
    pagina = _proveedor(respuestas).start_checkout(_orden())
    assert pagina.html == "<html></html>"
    cuerpo = json.loads(respuestas.peticiones[0].content)
    firmados = {k: v for k, v in cuerpo.items() if k not in ("tspay_signature", "firstName")}
    assert cuerpo["tspay_signature"] == order_signature(CLAVE, firmados)
    assert (cuerpo["amount"], cuerpo["country"], cuerpo["firstName"]) == ("32.00", "CO", "Ana")
    assert "merchant_code" not in cuerpo


def test_sin_pais_la_orden_no_lleva_country() -> None:
    respuestas = Respuestas(
        create_order_tspay=httpx.Response(201, text="<html></html>", headers={"Content-Type": "text/html"})
    )
    _proveedor(respuestas).start_checkout(_orden(method="cardtpv", country=None, buyer={}))
    cuerpo = json.loads(respuestas.peticiones[0].content)
    assert "country" not in cuerpo and "firstName" not in cuerpo


def test_una_orden_en_otra_moneda_no_sale() -> None:
    respuestas = Respuestas()
    with pytest.raises(CheckoutRejected):
        _proveedor(respuestas).start_checkout(_orden(currency="COP"))
    assert respuestas.peticiones == []


def test_un_400_es_rechazo_y_los_demas_errores_son_de_la_pasarela(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    rechazo = Respuestas(create_order_tspay=httpx.Response(400, json={"message": "Invalid signature"}))
    with pytest.raises(CheckoutRejected, match="Invalid signature"):
        _proveedor(rechazo).start_checkout(_orden())
    caida = Respuestas(create_order_tspay=httpx.Response(502, json={"message": "Ebanx"}))
    with pytest.raises(PaymentProviderError):
        _proveedor(caida).start_checkout(_orden())
    # El registro no lleva los datos del comprador ni las llaves.
    registros = "\n".join(r.getMessage() for r in caplog.records)
    assert "Ana" not in registros and CLAVE not in registros and "token-x" not in registros


def test_una_respuesta_201_que_no_es_html_no_se_sirve() -> None:
    respuestas = Respuestas(create_order_tspay=httpx.Response(201, json={"ok": True}))
    with pytest.raises(PaymentProviderError):
        _proveedor(respuestas).start_checkout(_orden())


def test_sin_red_el_error_no_lleva_lo_que_se_mandaba() -> None:
    def sin_red(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red", request=request)

    proveedor = TipsterPageProvider(
        base_url=SANDBOX_BASE_URL, merchant_code="m", auth_bearer="b", secret_key=CLAVE,
        transport=httpx.MockTransport(sin_red),
    )
    with pytest.raises(PaymentProviderError) as error:
        proveedor.start_checkout(_orden())
    assert "Ana" not in str(error.value) and error.value.__cause__ is None


# ---------- Catalogo ----------


def test_el_catalogo_se_traduce_y_descarta_lo_que_no_se_sabe_pedir() -> None:
    catalogo = [
        {"key": "cardtpv", "name": "Tarjeta", "logoUrl": "https://cdn/t.png", "priceMin": 1,
         "priceMax": 400, "countries": [], "fields": []},
        {"key": "pse", "name": "PSE", "logoUrl": "http://cdn/p.png", "priceMin": 1.5,
         "priceMax": 400, "countries": ["co"], "fields": ["firstName"]},
        {"key": "raro", "name": "Raro", "priceMin": 1, "priceMax": 9, "countries": [], "fields": ["email"]},
        {"key": "roto", "name": "Roto", "priceMin": "uno", "priceMax": 9},
    ]
    metodos = _proveedor(Respuestas(payment_methods=httpx.Response(200, json=catalogo))).payment_methods("CO")
    assert [(m.key, m.min_cents, m.max_cents, m.countries, m.fields) for m in metodos] == [
        ("cardtpv", 100, 40_000, (), ()),
        ("pse", 150, 40_000, ("CO",), ("firstName",)),
    ]
    # Un logo que no va por HTTPS no se muestra.
    assert (metodos[0].logo_url, metodos[1].logo_url) == ("https://cdn/t.png", None)


def test_sin_pais_quedan_solo_los_medios_sin_restriccion() -> None:
    catalogo = [
        {"key": "cardtpv", "name": "T", "priceMin": 1, "priceMax": 400, "countries": [], "fields": []},
        {"key": "bizum", "name": "B", "priceMin": 1, "priceMax": 400, "countries": ["ES"], "fields": []},
    ]
    respuestas = Respuestas(payment_methods=httpx.Response(200, json=catalogo))
    assert [m.key for m in _proveedor(respuestas).payment_methods(None)] == ["cardtpv"]
    assert "country-code" not in str(respuestas.peticiones[0].url)


def test_el_catalogo_se_guarda_unos_minutos() -> None:
    respuestas = Respuestas(payment_methods=httpx.Response(200, json=[]))
    proveedor = _proveedor(respuestas)
    proveedor.payment_methods("CO")
    proveedor.payment_methods("CO")
    proveedor.payment_methods("ES")
    assert len(respuestas.peticiones) == 2


def test_un_catalogo_que_no_es_una_lista_es_un_error() -> None:
    with pytest.raises(PaymentProviderError):
        _proveedor(Respuestas(payment_methods=httpx.Response(200, json={}))).payment_methods("CO")


# ---------- Aviso de pago ----------


def _aviso(paid_status="ok", order_id="SA-abc", amount="32", firma=None) -> bytes:
    firma = firma or notification_signature(CLAVE, paid_status, order_id, amount)
    return (
        f'{{"paid_status":"{paid_status}","order_id":"{order_id}","amount":{amount},'
        f'"nt_signature":"{firma}"}}'
    ).encode()


def test_un_aviso_bien_firmado() -> None:
    evento = _proveedor(Respuestas()).parse_event(_aviso(amount="12.5"), {})
    assert evento.signature_verified
    assert (evento.event_id, evento.transaction_id, evento.status, evento.event_type) == (
        "tipsterpage:SA-abc:ok",
        "SA-abc",
        "ok",
        "order.notification",
    )
    assert evento.payload == {
        "paid_status": "ok", "order_id": "SA-abc", "amount": 12.5,
        "nt_signature": notification_signature(CLAVE, "ok", "SA-abc", "12.5"),
    }


def test_la_firma_del_aviso_se_acepta_en_mayusculas() -> None:
    firma = notification_signature(CLAVE, "ko", "SA-abc", "32").upper()
    assert _proveedor(Respuestas()).parse_event(_aviso("ko", firma=firma), {}).signature_verified


def test_el_monto_reformateado_no_pasa() -> None:
    firma = notification_signature(CLAVE, "ok", "SA-abc", "12.5")
    evento = _proveedor(Respuestas()).parse_event(_aviso(amount="12.50", firma=firma), {})
    assert not evento.signature_verified
    assert evento.event_id.startswith("tipsterpage:invalid:")


@pytest.mark.parametrize(
    "cuerpo",
    [
        b"",
        b"[1]",
        b'{"paid_status":"ok"}',
        b'{"paid_status":"ok","order_id":"","amount":1,"nt_signature":"00"}',
        b'{"paid_status":"ok","order_id":"SA-abc","amount":32,"nt_signature":5}',
        b'{"paid_status":"","order_id":"SA-abc","amount":32,"nt_signature":"00"}',
        b'{"paid_status":null,"order_id":"SA-abc","amount":32,"nt_signature":"00"}',
        b'{"paid_status":1,"order_id":"SA-abc","amount":32,"nt_signature":"00"}',
        _aviso(paid_status="x" * 51),
    ],
)
def test_un_aviso_mal_formado_no_se_verifica(cuerpo: bytes) -> None:
    evento = _proveedor(Respuestas()).parse_event(cuerpo, {})
    assert not evento.signature_verified and not evento.notice_only


def test_un_aviso_de_devolucion_no_es_de_pago() -> None:
    """Respuesta de Tipster Page (2026-11-06): una devolucion manual pasa la
    orden a `refund` y avisa. Se acepta sin reconsultar ni mover nada."""
    evento = _proveedor(Respuestas()).parse_event(_aviso("refund"), {})
    assert evento.notice_only and evento.signature_verified
    assert (evento.event_id, evento.transaction_id, evento.status, evento.event_type) == (
        "tipsterpage:SA-abc:refund",
        None,
        "refund",
        "order.notice",
    )


@pytest.mark.parametrize(
    "cuerpo",
    [
        _aviso("refund", firma="00"),
        b'{"paid_status":"refund","order_id":"SA-abc"}',
        b'{"paid_status":"refund","order_id":"SA-abc","amount":32,"nt_signature":5}',
    ],
)
def test_un_aviso_de_devolucion_sin_firma_valida_tambien_es_un_aviso(cuerpo: bytes) -> None:
    """Sin firma valida tambien se acepta (no mueve nada), pero con el id de los
    no verificados: no ocupa el de un aviso autentico."""
    evento = _proveedor(Respuestas()).parse_event(cuerpo, {})
    assert evento.notice_only and not evento.signature_verified
    assert evento.event_id.startswith("tipsterpage:invalid:")
    assert (evento.transaction_id, evento.status) == (None, "refund")


# ---------- Reconsulta ----------


def _estado(texto: str, codigo: int = 200) -> Respuestas:
    return Respuestas(
        order_status=httpx.Response(codigo, content=texto.encode(), headers={"Content-Type": "application/json"})
    )


@pytest.mark.parametrize(
    ("estado", "esperado"),
    [
        ("paid", "approved"),
        ("pending", "pending"),
        ("error", "declined"),
        ("expired", "declined"),
        ("error_and_refund_payment", "declined"),
        ("fraud", "error"),
        ("algo-nuevo", "pending"),
    ],
)
def test_los_estados_de_la_orden(estado: str, esperado: str) -> None:
    respuestas = _estado(
        f'{{"amount":12.5,"paid_order_status":"{estado}","product_id":"mensual","product_name":"A"}}'
    )
    tx = _proveedor(respuestas).fetch_transaction("SA-abc")
    assert tx is not None
    assert (tx.id, tx.reference, tx.status, tx.amount_cents, tx.currency, tx.product_code) == (
        "SA-abc", "SA-abc", esperado, 1250, "EUR", "mensual",
    )
    assert respuestas.peticiones[0].url.path == "/tspayv2/order-status/SA-abc"


def test_una_orden_desconocida_es_none_y_un_401_es_un_error() -> None:
    assert _proveedor(_estado('{"message":"Order not found"}', 404)).fetch_transaction("x") is None
    with pytest.raises(PaymentProviderError):
        _proveedor(_estado('{"message":"Unauthorized"}', 401)).fetch_transaction("x")


@pytest.mark.parametrize("monto", ["32.001", "-1", '"treinta"', "null"])
def test_un_monto_ilegible_deja_la_transaccion_en_error(monto: str) -> None:
    tx = _proveedor(_estado(f'{{"amount":{monto},"paid_order_status":"paid"}}')).fetch_transaction("x")
    assert tx is not None and (tx.status, tx.amount_cents) == ("error", 0)


def test_el_id_de_la_orden_va_escapado_en_la_ruta() -> None:
    respuestas = _estado('{"amount":1,"paid_order_status":"paid"}')
    _proveedor(respuestas).fetch_transaction("SA/../x")
    assert respuestas.peticiones[0].url.raw_path == b"/tspayv2/order-status/SA%2F..%2Fx"


def test_lo_que_no_tiene() -> None:
    proveedor = _proveedor(Respuestas())
    assert proveedor.tokenizer() is None and proveedor.lookup_by_reference
    assert proveedor.describe() == "Tipster Page (sandbox)"


# ---------- Configuracion y arranque ----------


def _ajustes(**cambios) -> Settings:
    datos = {
        "payment_provider": "tipsterpage",
        "tspay_api_base_url": SANDBOX_BASE_URL,
        "tspay_merchant_code": "m",
        "tspay_auth_bearer": "b",
        "tspay_secret_key": "s",
        "api_public_url": "https://api.sebasanalisis.com",
        "frontend_base_url": "https://sebasanalisis.com",
        "email_backend": "smtp",
    }
    datos.update(cambios)
    return Settings(_env_file=None, **datos)


@pytest.mark.parametrize("falta", ["tspay_merchant_code", "tspay_auth_bearer", "tspay_secret_key"])
def test_sin_una_llave_no_arranca_y_dice_cual(falta: str) -> None:
    with pytest.raises(ProviderMisconfigured, match=falta.upper()):
        from_settings(_ajustes(**{falta: ""}))


def test_una_url_base_que_no_es_de_tipster_page_no_arranca() -> None:
    with pytest.raises(ProviderMisconfigured, match="TSPAY_API_BASE_URL"):
        from_settings(_ajustes(tspay_api_base_url="https://otro.com/tspayv2"))


def test_con_las_llaves_de_produccion_dice_el_ambiente() -> None:
    assert from_settings(_ajustes(tspay_api_base_url=PRODUCTION_BASE_URL + "/")).describe() == (
        "Tipster Page (PRODUCCION)"
    )


@pytest.mark.parametrize(
    ("cambios", "mensaje"),
    [
        ({"payment_provider": "fake"}, "PAYMENT_PROVIDER=fake"),
        ({"email_backend": "file"}, "EMAIL_BACKEND=file"),
        ({"api_public_url": "http://api.sebasanalisis.com"}, "API_PUBLIC_URL"),
        ({"frontend_base_url": "http://sebasanalisis.com"}, "FRONTEND_BASE_URL"),
    ],
)
def test_con_llaves_de_produccion_no_arranca_una_configuracion_de_desarrollo(cambios, mensaje) -> None:
    with pytest.raises(ProviderMisconfigured, match=mensaje):
        check_startup(_ajustes(tspay_api_base_url=PRODUCTION_BASE_URL, **cambios))


@pytest.mark.parametrize(
    ("cambios", "mensaje"),
    [
        ({"api_public_url": "api.sebasanalisis.com"}, "API_PUBLIC_URL"),
        ({"frontend_base_url": "sebasanalisis.com"}, "FRONTEND_BASE_URL"),
        ({"api_public_url": ""}, "API_PUBLIC_URL"),
    ],
)
def test_con_tipster_page_una_url_publica_sin_esquema_no_arranca(cambios, mensaje) -> None:
    """Tambien en el sandbox: sin el esquema, Tipster Page rechaza cada orden
    con "Invalid request data" (VPS, 2026-11-05)."""
    with pytest.raises(ProviderMisconfigured, match=mensaje):
        check_startup(_ajustes(**cambios))


def test_en_el_sandbox_las_url_locales_por_http_si_arrancan() -> None:
    check_startup(
        _ajustes(api_public_url="http://127.0.0.1:8000", frontend_base_url="http://localhost:3000")
    )


def test_con_las_del_sandbox_la_pasarela_simulada_y_el_correo_a_archivo_si_arrancan() -> None:
    check_startup(_ajustes(payment_provider="fake", email_backend="file", api_public_url="http://x"))


def test_la_aplicacion_arma_el_proveedor_desde_la_configuracion() -> None:
    from app.payments.base import build_payment_provider

    proveedor = build_payment_provider(_ajustes())
    assert isinstance(proveedor, TipsterPageProvider) and proveedor.base_url == SANDBOX_BASE_URL
    with pytest.raises(ProviderMisconfigured):
        build_payment_provider(
            _ajustes(payment_provider="fake", tspay_api_base_url=PRODUCTION_BASE_URL)
        )


def test_decimal_del_catalogo_sin_float() -> None:
    """`1.1` en el catalogo son 110 centavos, no 110.00000000000001."""
    catalogo = [{"key": "k", "name": "n", "priceMin": 1.1, "priceMax": 2.2, "countries": [], "fields": []}]
    [metodo] = _proveedor(Respuestas(payment_methods=httpx.Response(200, json=catalogo))).payment_methods(None)
    assert (metodo.min_cents, metodo.max_cents) == (110, 220)
    assert Decimal("1.1") * 100 == 110
