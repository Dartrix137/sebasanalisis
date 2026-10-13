"""Wompi: firmas, lectura de eventos y reconsulta. Sin red ni base.

Las cadenas que se firman salen de la documentacion oficial de Wompi consultada
el 2026-10-13 (las URL estan en `app/payments/wompi.py`). Estos tests fijan el
orden de la concatenacion: si alguien lo cambia de memoria, fallan.
"""

import hashlib
import json

import httpx
import pytest

from app.core.config import Settings
from app.payments.base import (
    PaymentProviderError,
    UnconfiguredPaymentProvider,
    build_payment_provider,
)
from app.payments.fake import FakePaymentProvider
from app.payments.wompi import (
    WompiProvider,
    event_checksum,
    integrity_signature,
    key_environment,
)

EVENTS_SECRET = "test_events_secreto-de-prueba"
INTEGRITY_SECRET = "test_integrity_secreto-de-prueba"

SANDBOX = {
    "wompi_public_key": "pub_test_abc",
    "wompi_private_key": "prv_test_abc",
    "wompi_events_secret": EVENTS_SECRET,
    "wompi_integrity_secret": INTEGRITY_SECRET,
}
PRODUCCION = {
    "wompi_public_key": "pub_prod_abc",
    "wompi_private_key": "prv_prod_abc",
    "wompi_events_secret": "prod_events_abc",
    "wompi_integrity_secret": "prod_integrity_abc",
}


def _settings(**campos) -> Settings:
    return Settings(_env_file=None, **campos)


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()


def _evento(**cambios) -> dict:
    """El evento de ejemplo de la documentacion de Wompi."""
    evento = {
        "event": "transaction.updated",
        "data": {
            "transaction": {
                "id": "1234-1610641025-49201",
                "amount_in_cents": 4490000,
                "reference": "MZQ3X2DE2SMX",
                "currency": "COP",
                "status": "APPROVED",
            }
        },
        "environment": "test",
        "signature": {
            "properties": ["transaction.id", "transaction.status", "transaction.amount_in_cents"],
            "checksum": "",
        },
        "timestamp": 1530291411,
        "sent_at": "2018-07-20T16:45:05.000Z",
    }
    evento.update(cambios)
    return evento


def _firmado(evento: dict) -> dict:
    evento["signature"]["checksum"] = event_checksum(evento, EVENTS_SECRET)
    return evento


def _provider(handler=None) -> WompiProvider:
    return WompiProvider(
        public_key="pub_test_abc",
        private_key="prv_test_abc",
        events_secret=EVENTS_SECRET,
        integrity_secret=INTEGRITY_SECRET,
        api_base_url="https://sandbox.wompi.co/v1",
        environment="sandbox",
        transport=httpx.MockTransport(handler) if handler else None,
    )


# ---------- Firma de integridad ----------


def test_firma_de_integridad_referencia_monto_moneda_secreto() -> None:
    firma = integrity_signature("SA-abc", 10_000_000, "COP", INTEGRITY_SECRET)
    assert firma == _sha(f"SA-abc10000000COP{INTEGRITY_SECRET}")


def test_el_checkout_lleva_la_firma_y_ningun_secreto() -> None:
    url = _provider().checkout_url(
        reference="SA-abc",
        amount_cents=10_000_000,
        currency="COP",
        redirect_url="https://sebasanalisis.com/pago/1",
        customer_email="ana@ejemplo.com",
    )
    query = dict(httpx.URL(url).params)
    assert url.startswith("https://checkout.wompi.co/p/?")
    assert query["public-key"] == "pub_test_abc"
    assert query["amount-in-cents"] == "10000000"
    assert query["currency"] == "COP"
    assert query["reference"] == "SA-abc"
    assert query["redirect-url"] == "https://sebasanalisis.com/pago/1"
    assert query["signature:integrity"] == integrity_signature(
        "SA-abc", 10_000_000, "COP", INTEGRITY_SECRET
    )
    for secreto in ("prv_test_abc", EVENTS_SECRET, INTEGRITY_SECRET):
        assert secreto not in url


# ---------- Checksum de un evento ----------


def test_checksum_del_evento_propiedades_timestamp_secreto() -> None:
    """La cadena del ejemplo de la documentacion, mas el secreto."""
    esperado = _sha(f"1234-1610641025-49201APPROVED44900001530291411{EVENTS_SECRET}")
    assert event_checksum(_evento(), EVENTS_SECRET) == esperado


def test_el_checksum_sigue_el_orden_de_properties_del_evento() -> None:
    """La lista de campos no es fija: se lee del evento."""
    evento = _evento()
    evento["signature"]["properties"] = ["transaction.amount_in_cents", "transaction.id"]
    esperado = _sha(f"44900001234-1610641025-492011530291411{EVENTS_SECRET}")
    assert event_checksum(evento, EVENTS_SECRET) == esperado


@pytest.mark.parametrize(
    "romper",
    [
        lambda e: e.pop("signature"),
        lambda e: e.pop("timestamp"),
        lambda e: e["signature"].update(properties=[]),
        lambda e: e["signature"].update(properties=["transaction.no_existe"]),
        lambda e: e["signature"].update(properties=["transaction"]),
        lambda e: e["signature"].update(properties=[7]),
        lambda e: e.update(data=None),
    ],
)
def test_sin_lo_necesario_no_hay_checksum(romper) -> None:
    evento = _evento()
    romper(evento)
    assert event_checksum(evento, EVENTS_SECRET) is None


def test_evento_con_firma_valida() -> None:
    evento = _firmado(_evento())
    cuerpo = json.dumps(evento).encode()
    leido = _provider().parse_event(cuerpo, {"X-Event-Checksum": evento["signature"]["checksum"]})

    assert leido.signature_verified is True
    assert leido.event_type == "transaction.updated"
    assert leido.transaction_id == "1234-1610641025-49201"
    assert leido.status == "APPROVED"
    assert leido.event_id == f"wompi:{evento['signature']['checksum']}"
    # El mismo evento reintentado trae el mismo id; uno posterior, otro.
    assert _provider().parse_event(cuerpo, {}).event_id == leido.event_id
    otro = _firmado(_evento(timestamp=1530291999))
    assert _provider().parse_event(json.dumps(otro).encode(), {}).event_id != leido.event_id


@pytest.mark.parametrize(
    "alterar",
    [
        # Firmado con otro secreto.
        lambda e: e["signature"].update(checksum=event_checksum(e, "test_events_otro")),
        lambda e: e["signature"].update(checksum="0" * 64),
        lambda e: e["signature"].update(checksum=None),
        # Firmado bien y despues alterado: otro estado, otro monto, otra transaccion.
        lambda e: e["data"]["transaction"].update(status="DECLINED"),
        lambda e: e["data"]["transaction"].update(amount_in_cents=1),
        lambda e: e["data"]["transaction"].update(id="otra"),
        lambda e: e.update(timestamp=1),
    ],
)
def test_evento_con_firma_invalida(alterar) -> None:
    evento = _firmado(_evento())
    alterar(evento)
    cuerpo = json.dumps(evento).encode()
    leido = _provider().parse_event(cuerpo, {})

    assert leido.signature_verified is False
    assert leido.transaction_id is None
    # Otro espacio de nombres: no puede ocupar el id de un evento autentico.
    assert leido.event_id == f"wompi:invalid:{hashlib.sha256(cuerpo).hexdigest()}"


def test_la_cabecera_tambien_debe_coincidir() -> None:
    evento = _firmado(_evento())
    cuerpo = json.dumps(evento).encode()
    assert _provider().parse_event(cuerpo, {"x-event-checksum": "0" * 64}).signature_verified is False


@pytest.mark.parametrize("cuerpo", [b"", b"no es json", b"[1, 2]", b'"texto"', b"\xff\xfe"])
def test_un_cuerpo_que_no_es_un_evento_no_rompe(cuerpo: bytes) -> None:
    leido = _provider().parse_event(cuerpo, {})
    assert leido.signature_verified is False
    assert leido.payload is None


# ---------- Reconsulta ----------


def test_reconsulta_con_la_llave_privada() -> None:
    vistos: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vistos.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "tx-1",
                    "reference": "SA-abc",
                    "status": "APPROVED",
                    "amount_in_cents": 10_000_000,
                    "currency": "COP",
                    "status_message": None,
                    "payment_method_type": "CARD",
                }
            },
        )

    tx = _provider(handler).fetch_transaction("tx-1")
    assert tx is not None
    assert (tx.id, tx.reference, tx.status, tx.amount_cents, tx.currency) == (
        "tx-1",
        "SA-abc",
        "approved",
        10_000_000,
        "COP",
    )
    assert str(vistos[0].url) == "https://sandbox.wompi.co/v1/transactions/tx-1"
    assert vistos[0].headers["Authorization"] == "Bearer prv_test_abc"


@pytest.mark.parametrize(
    ("de_wompi", "nuestro"),
    [
        ("PENDING", "pending"),
        ("APPROVED", "approved"),
        ("DECLINED", "declined"),
        ("VOIDED", "voided"),
        ("ERROR", "error"),
    ],
)
def test_estados_de_una_transaccion(de_wompi: str, nuestro: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        data = {"id": "t", "reference": "r", "status": de_wompi, "amount_in_cents": 5, "currency": "COP"}
        return httpx.Response(200, json={"data": data})

    tx = _provider(handler).fetch_transaction("t")
    assert tx is not None and tx.status == nuestro


def test_transaccion_que_wompi_no_conoce() -> None:
    assert _provider(lambda r: httpx.Response(404, json={})).fetch_transaction("x") is None


@pytest.mark.parametrize(
    "respuesta",
    [
        httpx.Response(500, text="error"),
        httpx.Response(401, json={"error": "no"}),
        httpx.Response(200, text="no es json"),
        httpx.Response(200, json={"data": {"id": "t"}}),
        # Un estado que la documentacion no lista no se interpreta.
        httpx.Response(
            200,
            json={"data": {"id": "t", "reference": "r", "status": "RARO", "amount_in_cents": 5, "currency": "COP"}},
        ),
        # Ni un monto que no sea un entero de centavos.
        httpx.Response(
            200,
            json={"data": {"id": "t", "reference": "r", "status": "APPROVED", "amount_in_cents": "5", "currency": "COP"}},
        ),
    ],
)
def test_una_respuesta_que_no_se_entiende_es_un_error(respuesta: httpx.Response) -> None:
    with pytest.raises(PaymentProviderError):
        _provider(lambda r: respuesta).fetch_transaction("t")


def test_wompi_caido_es_un_error_y_no_muestra_la_llave() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red")

    with pytest.raises(PaymentProviderError) as exc:
        _provider(handler).fetch_transaction("t")
    assert "prv_test_abc" not in str(exc.value)


# ---------- Configuracion ----------


def test_sin_llaves_el_pago_queda_apagado() -> None:
    provider = build_payment_provider(_settings())
    assert isinstance(provider, UnconfiguredPaymentProvider)
    assert provider.enabled is False


def test_llaves_de_sandbox() -> None:
    provider = build_payment_provider(_settings(**SANDBOX))
    assert isinstance(provider, WompiProvider)
    assert provider.environment == "sandbox"
    assert provider.api_base_url == "https://sandbox.wompi.co/v1"
    # Lo que va al log de arranque dice el ambiente y ninguna llave.
    descripcion = provider.describe()
    assert "sandbox" in descripcion
    for valor in SANDBOX.values():
        assert valor not in descripcion


def test_llaves_de_produccion() -> None:
    assert key_environment(_settings(**PRODUCCION)) == "production"


@pytest.mark.parametrize(
    "campos",
    [
        # Falta una.
        {**SANDBOX, "wompi_events_secret": ""},
        # Sandbox y produccion revueltas.
        {**SANDBOX, "wompi_private_key": "prv_prod_abc"},
        # La llave privada en el lugar de la publica.
        {**SANDBOX, "wompi_public_key": "prv_test_abc"},
        # La URL no es la del ambiente de las llaves.
        {**SANDBOX, "wompi_api_base_url": "https://production.wompi.co/v1"},
        {**PRODUCCION, "wompi_api_base_url": "https://sandbox.wompi.co/v1"},
    ],
)
def test_llaves_incompletas_o_mezcladas_no_arrancan(campos: dict) -> None:
    with pytest.raises(ValueError) as exc:
        build_payment_provider(_settings(**campos))
    for valor in campos.values():
        if valor:
            assert valor not in str(exc.value)


def test_la_pasarela_simulada_no_convive_con_llaves_de_produccion() -> None:
    assert isinstance(
        build_payment_provider(_settings(payment_provider="fake")), FakePaymentProvider
    )
    assert isinstance(
        build_payment_provider(_settings(payment_provider="fake", **SANDBOX)), FakePaymentProvider
    )
    with pytest.raises(ValueError):
        build_payment_provider(_settings(payment_provider="fake", **PRODUCCION))
