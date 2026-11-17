"""Firma de las suscripciones de Tipster Page (`tspay-subscriptions.md`, 2026-11-17).

Los dos vectores salen del documento de Tipster Page (§2.5 y §3.3), con su
clave de ejemplo `test_secret`: el texto canonico y la firma esperada que ellos
publicaron, no lo que calcula el codigo que se prueba.
"""

import json
from decimal import Decimal

import pytest

from app.payments.tipsterpage_signing import (
    amount_number,
    canonical_json,
    request_signature,
    signed_body,
    verified_notification,
)

CLAVE = "test_secret"

# Suscripciones §2.5: el alta del ejemplo, con `amount` escrito 9.90.
ALTA = {
    "idempotency_key": "0f8fad5b-d9cb-469f-a165-70867728950e",
    "external_id": "cliente-42",
    "product_id": "plan-mensual",
    "product_name": "Plan mensual",
    "amount": 9.90,
    "periodicity": "mensual",
    "email": "comprador@example.com",
    "country": "ES",
    "language": "es",
    "url_ok": "https://comercio.example/ok",
    "url_ko": "https://comercio.example/ko",
    "notification_url": "https://comercio.example/notificaciones",
    "terms_accepted": True,
}
ALTA_CANONICA = (
    '{"action":"CREATE","merchant":"MI_COMERCIO","parameters":{"amount":9.9,"country":"ES",'
    '"email":"comprador@example.com","external_id":"cliente-42",'
    '"idempotency_key":"0f8fad5b-d9cb-469f-a165-70867728950e","language":"es",'
    '"notification_url":"https://comercio.example/notificaciones","periodicity":"mensual",'
    '"product_id":"plan-mensual","product_name":"Plan mensual","terms_accepted":true,'
    '"url_ko":"https://comercio.example/ko","url_ok":"https://comercio.example/ok"},'
    '"resource":""}'
)
ALTA_FIRMA = "cd024183954f965049a3deb96939a916d1fea297bb0aa19a5e2807bfcb2d7c65"

# Suscripciones §3.3: el aviso de renovacion, tal como llega.
AVISO = (
    b'{"event_id":"6f1c2a7e9b0d4c3a8e5f1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60",'
    b'"event_type":"subscription.renewed","subscription_id":"b3c1e7a2-5d4f-4e8a-9c1b-2f3e4d5c6b7a",'
    b'"external_id":"cliente-42","occurred_at":"2026-12-17T10:00:00.000Z","data":{'
    b'"payment_id":"a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d","period_id":"2026-12","cycle":2,'
    b'"amount":9.9,"currency":"EUR","paid_status":"paid","error_code":null,'
    b'"retry_allowed":false,"authentication_required":false},'
    b'"nt_signature":"48a65ac9c79fee1468c66d4d49328591e0b8b0e8e3993740c6eecceacd459bdc"}'
)


# ---------------------------------------------------------------- peticiones


def test_texto_canonico_del_alta_es_el_del_documento() -> None:
    texto = canonical_json(
        {"merchant": "MI_COMERCIO", "action": "CREATE", "resource": "", "parameters": ALTA}
    )
    assert texto == ALTA_CANONICA


def test_firma_del_alta_es_la_del_documento() -> None:
    assert request_signature(CLAVE, "MI_COMERCIO", "CREATE", "", ALTA) == ALTA_FIRMA


def test_el_comercio_se_firma_sin_espacios_en_los_bordes() -> None:
    assert request_signature(CLAVE, "  MI_COMERCIO ", "CREATE", "", ALTA) == ALTA_FIRMA


def test_cambiar_la_accion_o_el_recurso_cambia_la_firma() -> None:
    otra_accion = request_signature(CLAVE, "MI_COMERCIO", "UPDATE", "", ALTA)
    otro_recurso = request_signature(CLAVE, "MI_COMERCIO", "CREATE", "abc", ALTA)
    assert ALTA_FIRMA not in (otra_accion, otro_recurso)


def test_cuerpo_firmado_lleva_los_parametros_y_la_firma() -> None:
    cuerpo = signed_body(CLAVE, "MI_COMERCIO", "CREATE", "", ALTA)
    assert cuerpo == {**ALTA, "tspay_signature": ALTA_FIRMA}


def test_la_firma_no_entra_en_lo_que_se_firma() -> None:
    with pytest.raises(ValueError):
        request_signature(CLAVE, "MI_COMERCIO", "CREATE", "", {**ALTA, "tspay_signature": "x"})


def test_canonico_no_escapa_barras_ni_tildes() -> None:
    assert canonical_json({"b": "Suscripción €/mes", "a": 1}) == '{"a":1,"b":"Suscripción €/mes"}'


def test_canonico_ordena_las_claves_anidadas() -> None:
    assert canonical_json({"z": {"b": 1, "a": [{"d": 2, "c": 3}]}}) == (
        '{"z":{"a":[{"c":3,"d":2}],"b":1}}'
    )


def test_canonico_rechaza_nan() -> None:
    with pytest.raises(ValueError):
        canonical_json({"amount": float("nan")})


# ---------------------------------------------------------------- montos


@pytest.mark.parametrize(
    ("centavos", "texto"),
    [(3200, "32"), (4600, "46"), (990, "9.9"), (1250, "12.5"), (1, "0.01"), (7, "0.07"), (199, "1.99")],
)
def test_monto_en_su_forma_mas_corta(centavos: int, texto: str) -> None:
    assert json.dumps(amount_number(centavos)) == texto


def test_todo_monto_de_hasta_diez_mil_euros_se_escribe_como_su_decimal() -> None:
    # `n / 100` tiene que escribirse con los digitos del decimal exacto, como
    # JSON.stringify: si no, la firma no coincide con la del servidor.
    for centavos in range(1, 1_000_001):
        esperado = Decimal(centavos) / 100
        assert Decimal(json.dumps(amount_number(centavos))) == esperado


@pytest.mark.parametrize("malo", [0, -100])
def test_monto_no_positivo_se_rechaza(malo: int) -> None:
    with pytest.raises(ValueError):
        amount_number(malo)


@pytest.mark.parametrize("malo", [32.0, True, Decimal("32")])
def test_monto_que_no_es_entero_en_centavos_se_rechaza(malo: object) -> None:
    with pytest.raises(TypeError):
        amount_number(malo)  # type: ignore[arg-type]


# ---------------------------------------------------------------- avisos


def test_aviso_del_documento_se_verifica() -> None:
    aviso = verified_notification(CLAVE, AVISO)
    assert aviso is not None
    assert aviso["event_type"] == "subscription.renewed"
    assert aviso["data"]["amount"] == 9.9
    assert "nt_signature" not in aviso


def test_aviso_con_las_claves_en_otro_orden_se_verifica() -> None:
    desordenado = json.dumps(dict(reversed(list(json.loads(AVISO).items())))).encode()
    assert verified_notification(CLAVE, desordenado) is not None


def test_aviso_con_otra_clave_no_se_verifica() -> None:
    assert verified_notification("otra_clave", AVISO) is None


def test_aviso_alterado_no_se_verifica() -> None:
    assert verified_notification(CLAVE, AVISO.replace(b'"cycle":2', b'"cycle":3')) is None


def test_aviso_con_el_monto_reescrito_no_se_verifica() -> None:
    # 9.90 se lee como 9.9 y vuelve a firmar igual; 9.91 no.
    assert verified_notification(CLAVE, AVISO.replace(b'"amount":9.9', b'"amount":9.90')) is not None
    assert verified_notification(CLAVE, AVISO.replace(b'"amount":9.9', b'"amount":9.91')) is None


@pytest.mark.parametrize(
    "cuerpo",
    [
        b"",
        b"no es json",
        b"[]",
        b'{"event_id":"x"}',
        b'{"event_id":"x","nt_signature":5}',
        b'{"event_id":"x","nt_signature":"\xc3\xa9"}',
        b'{"amount":NaN,"nt_signature":"00"}',
        b"\xff\xfe",
    ],
)
def test_aviso_malformado_no_se_verifica_ni_lanza(cuerpo: bytes) -> None:
    assert verified_notification(CLAVE, cuerpo) is None
