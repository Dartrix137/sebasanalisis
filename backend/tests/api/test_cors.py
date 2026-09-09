"""CORS: sin esto el frontend en otro puerto no puede llamar la API.

Los demas tests corren con TestClient en proceso y no lo detectan; este verifica
explicitamente que la cabecera salga.
"""

from fastapi.testclient import TestClient


def test_preflight_permite_el_origen_del_frontend(client: TestClient) -> None:
    r = client.options(
        "/auth/login",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_origen_no_autorizado_no_recibe_la_cabecera(client: TestClient) -> None:
    r = client.get("/health", headers={"Origin": "http://sitio-ajeno.example"})
    assert "access-control-allow-origin" not in r.headers
