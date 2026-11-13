"""La API no arranca con secretos de ejemplo (`config.check_secrets`).

Auditoria de seguridad del 2026-11-12, pista 1: la clave de los JWT y la del
administrador inicial tenian valores de ejemplo publicos que nada rechazaba.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import InsecureConfiguration, Settings, check_secrets, get_settings

CLAVE_BUENA = "x" * 32


def _ajustes(**cambios: str) -> Settings:
    valores = {"jwt_secret_key": CLAVE_BUENA, "seed_admin_password": ""} | cambios
    return Settings(_env_file=None, **valores)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("clave", "motivo"),
    [
        ("", "no esta definida"),
        ("   ", "no esta definida"),
        ("cambia-esto-en-produccion", "valor de ejemplo"),
        (" cambia-esto-en-produccion ", "valor de ejemplo"),
        ("x" * 31, "al menos 32"),
    ],
)
def test_clave_de_jwt_que_no_sirve(clave: str, motivo: str) -> None:
    with pytest.raises(InsecureConfiguration, match=motivo) as error:
        check_secrets(_ajustes(jwt_secret_key=clave))
    # El mensaje nombra la variable, nunca el valor.
    assert "JWT_SECRET_KEY" in str(error.value)
    if clave.strip():
        assert clave.strip() not in str(error.value)


def test_clave_del_admin_de_ejemplo() -> None:
    with pytest.raises(InsecureConfiguration, match="SEED_ADMIN_PASSWORD"):
        check_secrets(_ajustes(seed_admin_password="cambia-esta-clave"))


def test_configuracion_valida() -> None:
    check_secrets(_ajustes())
    # Sin clave del administrador arranca: la API no la usa.
    check_secrets(_ajustes(seed_admin_password=""))
    check_secrets(_ajustes(seed_admin_password="otra-clave-larga-y-propia"))


@pytest.fixture
def clave_de_ejemplo(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("JWT_SECRET_KEY", "cambia-esto-en-produccion")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.mark.usefixtures("clave_de_ejemplo")
def test_el_servidor_no_arranca_con_la_clave_de_ejemplo() -> None:
    from app.main import app

    with pytest.raises(InsecureConfiguration), TestClient(app):
        pass
    # Importar la app sigue funcionando (lo hace `gen:types`): la comprobacion
    # corre al levantar el servidor.
    assert app.openapi()["info"]["title"]
