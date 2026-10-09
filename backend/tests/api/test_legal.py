"""Legal: documentos versionados, consentimientos y re-aceptacion (§6 de la Fase 4).

Los tests comparten la base de la corrida: publicar una version nueva en uno la
deja publicada para los siguientes. Por eso cada test registra sus cuentas
despues de preparar lo que necesita, y nunca supone que la version vigente es
la 1.
"""

import re
import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.access import has_access
from app.models import User
from tests.api.conftest import OPEN_PREFIXES, auth, consent_fields
from tests.api.test_spins import _crear_sesion, variant_id  # noqa: F401, I001

PASSWORD = "clave-segura-123"
# Un resultado que existe en la ruleta mini de `test_spins`.
NUMERO = "1"


def _email() -> str:
    return f"legal-{uuid.uuid4().hex[:12]}@ejemplo.com"


def _register(client: TestClient, email: str | None = None) -> dict:
    r = client.post("/auth/register", json={"email": email or _email(), "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()


def _publish(
    client: TestClient, admin_token: str, kind: str, *, requires_acceptance: bool = True
) -> dict:
    """Publica una version nueva de `kind` y la devuelve."""
    body = {
        "kind": kind,
        "title": f"Documento {kind} de prueba",
        "content_md": f"## Texto de prueba\n\n{uuid.uuid4().hex}",
        "requires_acceptance": requires_acceptance,
    }
    r = client.post("/admin/legal-documents", json=body, headers=auth(admin_token))
    assert r.status_code == 201, r.text
    r = client.post(f"/admin/legal-documents/{r.json()['id']}/publish", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    return r.json()


# ---------- Paginas publicas ----------


def test_la_migracion_deja_publicados_los_cuatro_borradores(client: TestClient) -> None:
    for kind in ("terms", "privacy", "refunds", "cookies"):
        r = client.get(f"/legal/{kind}")
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["kind"] == kind
        assert doc["version"] >= 1
        assert doc["published_at"]


def test_los_borradores_iniciales_dicen_que_son_borradores(db) -> None:
    rows = db.execute(
        text("SELECT kind, content_md FROM legal_documents WHERE version = 1")
    ).all()
    assert {kind for kind, _ in rows} == {"terms", "privacy", "refunds", "cookies"}
    for _, content in rows:
        primer_parrafo = content.split("\n\n")[0]
        assert "BORRADOR" in primer_parrafo
        assert "pendiente de revisión por un abogado" in primer_parrafo


def test_los_borradores_iniciales_cubren_el_contenido_minimo(db) -> None:
    """§6.5: lo que el producto necesita que digan los textos."""
    terms = db.execute(
        text("SELECT content_md FROM legal_documents WHERE kind = 'terms' AND version = 1")
    ).scalar_one()
    for frase in (
        "no es una predicción",
        "no garantiza ningún resultado",
        "no la probabilidad de acertar",
        "Cada giro es independiente",
        "Ninguna gestión de banca cambia la ventaja de la casa",
        "no es un operador de juegos de suerte y azar",
        "No recibe apuestas",
        "no paga premios",
        "mayores de edad",
        "responsable de los números que ingresas",
        "Renovación automática",
    ):
        assert frase in terms, frase

    privacy = db.execute(
        text("SELECT content_md FROM legal_documents WHERE kind = 'privacy' AND version = 1")
    ).scalar_one()
    for frase in (
        "sebas.analisis.ia.com@gmail.com",
        "Resend",
        "GlitchTip",
        "último número en cero",
        "Ley 1581",
    ):
        assert frase in privacy, frase

    cookies = db.execute(
        text("SELECT content_md FROM legal_documents WHERE kind = 'cookies' AND version = 1")
    ).scalar_one()
    assert "localStorage" in cookies
    assert "No hay analítica de terceros" in cookies

    refunds = db.execute(
        text("SELECT content_md FROM legal_documents WHERE kind = 'refunds' AND version = 1")
    ).scalar_one()
    assert "Ley 1480" in refunds


def test_un_tipo_de_documento_desconocido_no_existe(client: TestClient) -> None:
    assert client.get("/legal/responsible_gaming").status_code == 422


def test_un_borrador_sin_publicar_no_se_ve_en_la_pagina_publica(
    client: TestClient, admin_token: str
) -> None:
    antes = client.get("/legal/cookies").json()
    r = client.post(
        "/admin/legal-documents",
        json={
            "kind": "cookies",
            "title": "Cookies en preparación",
            "content_md": "texto que todavía no es público",
            "requires_acceptance": False,
        },
        headers=auth(admin_token),
    )
    assert r.status_code == 201, r.text
    assert client.get("/legal/cookies").json()["id"] == antes["id"]

    # Publicado, pasa a ser el vigente.
    client.post(f"/admin/legal-documents/{r.json()['id']}/publish", headers=auth(admin_token))
    ahora = client.get("/legal/cookies").json()
    assert ahora["id"] == r.json()["id"]
    assert ahora["version"] == antes["version"] + 1


# ---------- Registro ----------


def test_registro_sin_consentimientos_es_rechazado(client: TestClient) -> None:
    """Hecho-cuando del paso 2: sin las casillas no hay cuenta."""
    email = _email()
    # `request` y no `post`: el `post` de los tests agrega los consentimientos.
    r = client.request("POST", "/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 422, r.text
    assert "mayor de edad" in r.json()["detail"]
    # No quedo ninguna cuenta a medias.
    assert client.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401


def test_registro_sin_mayoria_de_edad_es_rechazado(client: TestClient) -> None:
    email = _email()
    body = {"email": email, "password": PASSWORD, **consent_fields(client), "adult_confirmed": False}
    r = client.post("/auth/register", json=body)
    assert r.status_code == 422
    assert "mayor de edad" in r.json()["detail"]
    assert client.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401


def test_registro_al_que_le_falta_un_documento_es_rechazado(client: TestClient) -> None:
    required = client.get("/legal/required").json()
    assert {d["kind"] for d in required} == {"terms", "privacy"}

    for falta in required:
        email = _email()
        ids = [d["id"] for d in required if d["id"] != falta["id"]]
        r = client.post(
            "/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "accepted_document_ids": ids,
                "adult_confirmed": True,
            },
        )
        assert r.status_code == 422, falta["kind"]
        assert "Términos y Condiciones" in r.json()["detail"]
        assert (
            client.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code
            == 401
        )


def test_registro_guarda_un_consentimiento_por_documento_con_ip_y_navegador(
    client: TestClient, db
) -> None:
    required = client.get("/legal/required").json()
    r = client.post(
        "/auth/register",
        json={"email": _email(), "password": PASSWORD, **consent_fields(client)},
        headers={"User-Agent": "NavegadorDePrueba/1.0"},
    )
    assert r.status_code == 201, r.text
    user = r.json()["user"]
    assert user["adult_confirmed_at"] is not None
    assert user["onboarding_completed_at"] is None

    rows = db.execute(
        text(
            "SELECT legal_document_id, ip, user_agent, accepted_at "
            "FROM user_consents WHERE user_id = :u"
        ),
        {"u": user["id"]},
    ).all()
    assert {str(row[0]) for row in rows} == {d["id"] for d in required}
    for _, ip, user_agent, accepted_at in rows:
        assert ip == "testclient"
        assert user_agent == "NavegadorDePrueba/1.0"
        assert accepted_at is not None


def test_registro_no_guarda_aceptaciones_de_documentos_que_no_se_piden(
    client: TestClient, db
) -> None:
    refunds = client.get("/legal/refunds").json()
    campos = consent_fields(client)
    campos["accepted_document_ids"].append(refunds["id"])
    r = client.post("/auth/register", json={"email": _email(), "password": PASSWORD, **campos})
    assert r.status_code == 201, r.text

    aceptados = db.execute(
        text("SELECT legal_document_id FROM user_consents WHERE user_id = :u"),
        {"u": r.json()["user"]["id"]},
    ).scalars()
    assert refunds["id"] not in {str(i) for i in aceptados}


def test_cuenta_recien_registrada_no_tiene_nada_pendiente(client: TestClient) -> None:
    token = _register(client)["access_token"]
    r = client.get("/legal/pending", headers=auth(token))
    assert r.status_code == 200
    assert r.json() == {"documents": [], "adult_confirmation_required": False}
    assert client.get("/sessions", headers=auth(token)).status_code == 200


# ---------- Re-aceptacion ----------


def test_version_nueva_pide_re_aceptacion(client: TestClient, admin_token: str) -> None:
    """Hecho-cuando del paso 2: publicar una version que exige aceptacion corta
    el acceso a la mesa hasta aceptarla, sin bloquear la cuenta."""
    token = _register(client)["access_token"]
    assert client.get("/sessions", headers=auth(token)).status_code == 200

    nueva = _publish(client, admin_token, "terms")

    r = client.get("/sessions", headers=auth(token))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "consent_required"

    pendiente = client.get("/legal/pending", headers=auth(token)).json()
    assert [d["id"] for d in pendiente["documents"]] == [nueva["id"]]
    assert pendiente["adult_confirmation_required"] is False

    # La cuenta no queda bloqueada: perfil, documentos aceptados y exportacion.
    assert client.get("/auth/me", headers=auth(token)).status_code == 200
    assert client.get("/legal/consents", headers=auth(token)).status_code == 200
    assert client.get("/auth/me/export", headers=auth(token)).status_code == 200

    r = client.post(
        "/legal/accept", json={"legal_document_ids": [nueva["id"]]}, headers=auth(token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["documents"] == []
    assert client.get("/sessions", headers=auth(token)).status_code == 200


def test_version_nueva_que_no_exige_aceptacion_no_pide_nada(
    client: TestClient, admin_token: str
) -> None:
    token = _register(client)["access_token"]
    _publish(client, admin_token, "privacy", requires_acceptance=False)

    assert client.get("/legal/pending", headers=auth(token)).json()["documents"] == []
    assert client.get("/sessions", headers=auth(token)).status_code == 200
    # Y una cuenta nueva acepta esa version, que es la vigente, y queda al dia.
    nuevo = _register(client)["access_token"]
    assert client.get("/sessions", headers=auth(nuevo)).status_code == 200


def test_no_se_puede_aceptar_una_version_que_ya_no_es_la_vigente(
    client: TestClient, admin_token: str
) -> None:
    token = _register(client)["access_token"]
    vieja = _publish(client, admin_token, "terms")
    _publish(client, admin_token, "terms")

    r = client.post(
        "/legal/accept", json={"legal_document_ids": [vieja["id"]]}, headers=auth(token)
    )
    assert r.status_code == 409
    assert client.get("/sessions", headers=auth(token)).status_code == 403


def test_aceptar_dos_veces_no_duplica_el_consentimiento(
    client: TestClient, admin_token: str, db
) -> None:
    registro = _register(client)
    token = registro["access_token"]
    nueva = _publish(client, admin_token, "terms")
    for _ in range(2):
        r = client.post(
            "/legal/accept", json={"legal_document_ids": [nueva["id"]]}, headers=auth(token)
        )
        assert r.status_code == 200, r.text

    veces = db.execute(
        text(
            "SELECT count(*) FROM user_consents "
            "WHERE user_id = :u AND legal_document_id = :d"
        ),
        {"u": registro["user"]["id"], "d": nueva["id"]},
    ).scalar_one()
    assert veces == 1


def test_cuenta_anterior_al_paso_2_debe_aceptar_y_declarar_mayoria_de_edad(
    client: TestClient, db
) -> None:
    """Las cuentas que ya existian no tienen consentimientos: no se les inventan."""
    registro = _register(client)
    token, user_id = registro["access_token"], registro["user"]["id"]
    db.execute(text("DELETE FROM user_consents WHERE user_id = :u"), {"u": user_id})
    db.execute(text("UPDATE users SET adult_confirmed_at = NULL WHERE id = :u"), {"u": user_id})
    db.commit()

    r = client.get("/sessions", headers=auth(token))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "consent_required"
    pendiente = client.get("/legal/pending", headers=auth(token)).json()
    assert {d["kind"] for d in pendiente["documents"]} == {"terms", "privacy"}
    assert pendiente["adult_confirmation_required"] is True

    # Aceptar los documentos sin declarar la mayoria de edad no alcanza.
    ids = [d["id"] for d in pendiente["documents"]]
    r = client.post("/legal/accept", json={"legal_document_ids": ids}, headers=auth(token))
    assert r.json() == {"documents": [], "adult_confirmation_required": True}
    assert client.get("/sessions", headers=auth(token)).status_code == 403

    r = client.post("/legal/accept", json={"adult_confirmed": True}, headers=auth(token))
    assert r.json() == {"documents": [], "adult_confirmation_required": False}
    assert client.get("/sessions", headers=auth(token)).status_code == 200
    assert client.get("/auth/me", headers=auth(token)).json()["adult_confirmed_at"] is not None


def test_un_administrador_tambien_debe_aceptar(client: TestClient, admin_token: str) -> None:
    """§2.2: el consentimiento va antes que el rol."""
    _publish(client, admin_token, "terms")
    r = client.get("/games", headers=auth(admin_token))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "consent_required"
    # El panel legal no depende del acceso a la mesa.
    assert client.get("/admin/legal-documents", headers=auth(admin_token)).status_code == 200


# ---------- Control de acceso ----------

def test_todos_los_routers_de_juego_exigen_el_consentimiento(
    client: TestClient, admin_token: str
) -> None:
    """Recorre TODAS las rutas de juego con una cuenta sin el consentimiento
    vigente. Un router nuevo que olvide `RequireAccess` rompe este test en vez
    de quedar abierto (§2.4)."""
    from app.main import app

    token = _register(client)["access_token"]
    _publish(client, admin_token, "terms")

    # Las rutas salen del OpenAPI: es la lista de lo que la API publica, sin
    # depender de como FastAPI guarda por dentro los routers incluidos.
    probadas = 0
    for ruta, operaciones in app.openapi()["paths"].items():
        if ruta.startswith(OPEN_PREFIXES):
            continue
        path = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), ruta)
        for method in operaciones:
            r = client.request(method.upper(), path, headers=auth(token))
            assert r.status_code == 403, f"{method} {ruta} respondió {r.status_code}"
            assert r.json()["detail"]["code"] == "consent_required", f"{method} {ruta}"
            probadas += 1
    # Si la cuenta baja, alguien movio las rutas de juego a un prefijo "abierto".
    assert probadas >= 25


def test_has_access_decide_por_el_consentimiento(client: TestClient, admin_token: str, db) -> None:
    registro = _register(client)
    user = db.get(User, uuid.UUID(registro["user"]["id"]))
    now = datetime.now(UTC)

    decision = has_access(db, user, now)
    assert (decision.granted, decision.reason) == (True, "invited")

    _publish(client, admin_token, "privacy")
    decision = has_access(db, user, now)
    assert (decision.granted, decision.reason) == (False, "consent_required")


# ---------- Admin ----------


def test_una_version_publicada_no_se_edita(client: TestClient, admin_token: str) -> None:
    publicada = _publish(client, admin_token, "refunds", requires_acceptance=False)
    r = client.patch(
        f"/admin/legal-documents/{publicada['id']}",
        json={"title": "Otro título", "content_md": "otro texto", "requires_acceptance": False},
        headers=auth(admin_token),
    )
    assert r.status_code == 409
    assert client.get("/legal/refunds").json()["content_md"] == publicada["content_md"]

    r = client.post(
        f"/admin/legal-documents/{publicada['id']}/publish", headers=auth(admin_token)
    )
    assert r.status_code == 409


def test_un_borrador_se_edita_y_su_version_es_la_siguiente(
    client: TestClient, admin_token: str
) -> None:
    vigente = client.get("/legal/refunds").json()
    body = {
        "kind": "refunds",
        "title": "Reembolsos",
        "content_md": "primer texto",
        "requires_acceptance": False,
    }
    r = client.post("/admin/legal-documents", json=body, headers=auth(admin_token))
    assert r.status_code == 201, r.text
    borrador = r.json()
    assert borrador["version"] == vigente["version"] + 1
    assert borrador["published_at"] is None

    # Un solo borrador por documento.
    assert (
        client.post("/admin/legal-documents", json=body, headers=auth(admin_token)).status_code
        == 409
    )

    r = client.patch(
        f"/admin/legal-documents/{borrador['id']}",
        json={"title": "Reembolsos", "content_md": "texto corregido", "requires_acceptance": False},
        headers=auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["content_md"] == "texto corregido"

    r = client.post(f"/admin/legal-documents/{borrador['id']}/publish", headers=auth(admin_token))
    assert r.status_code == 200
    assert client.get("/legal/refunds").json()["content_md"] == "texto corregido"

    versiones = client.get(
        "/admin/legal-documents", params={"kind": "refunds"}, headers=auth(admin_token)
    ).json()
    assert [v["version"] for v in versiones] == sorted(
        (v["version"] for v in versiones), reverse=True
    )
    assert versiones[0]["id"] == borrador["id"]


def test_el_panel_legal_es_solo_para_administradores(client: TestClient, user_token: str) -> None:
    headers = auth(user_token)
    body = {"kind": "terms", "title": "x", "content_md": "x", "requires_acceptance": True}
    documento = client.get("/legal/terms").json()["id"]
    assert client.get("/admin/legal-documents", headers=headers).status_code == 403
    assert client.post("/admin/legal-documents", json=body, headers=headers).status_code == 403
    assert (
        client.patch(f"/admin/legal-documents/{documento}", json=body, headers=headers).status_code
        == 403
    )
    assert (
        client.post(f"/admin/legal-documents/{documento}/publish", headers=headers).status_code
        == 403
    )
    assert client.get("/admin/legal-documents").status_code == 401


# ---------- Cuenta: onboarding, documentos aceptados, exportacion ----------


def test_onboarding_se_anota_una_sola_vez(client: TestClient) -> None:
    token = _register(client)["access_token"]
    r = client.post("/auth/me/onboarding", headers=auth(token))
    assert r.status_code == 200, r.text
    primera = r.json()["onboarding_completed_at"]
    assert primera is not None
    r = client.post("/auth/me/onboarding", headers=auth(token))
    assert r.json()["onboarding_completed_at"] == primera


def test_documentos_aceptados_marca_cual_sigue_vigente(
    client: TestClient, admin_token: str
) -> None:
    token = _register(client)["access_token"]
    aceptados = client.get("/legal/consents", headers=auth(token)).json()
    assert {c["kind"] for c in aceptados} == {"terms", "privacy"}
    assert all(c["current"] for c in aceptados)

    _publish(client, admin_token, "terms")
    aceptados = client.get("/legal/consents", headers=auth(token)).json()
    assert {c["kind"]: c["current"] for c in aceptados} == {"terms": False, "privacy": True}


def test_exportar_devuelve_solo_los_datos_de_la_cuenta(
    client: TestClient,
    variant_id: str,  # noqa: F811
) -> None:
    propio = _register(client)
    ajeno = _register(client)
    sesion = _crear_sesion(client, propio["access_token"], variant_id).json()["id"]
    r = client.post(
        f"/sessions/{sesion}/spins",
        json={"result_value": NUMERO},
        headers=auth(propio["access_token"]),
    )
    assert r.status_code == 201, r.text
    otra = _crear_sesion(client, ajeno["access_token"], variant_id).json()["id"]

    r = client.get("/auth/me/export", headers=auth(propio["access_token"]))
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["account"]["email"] == propio["user"]["email"]
    assert [s["session"]["id"] for s in datos["sessions"]] == [sesion]
    assert [sp["result_value"] for sp in datos["sessions"][0]["spins"]] == [NUMERO]
    assert {c["kind"] for c in datos["consents"]} == {"terms", "privacy"}
    assert datos["payments"] == []
    assert otra not in r.text
    assert "password" not in r.text

    assert client.get("/auth/me/export").status_code == 401


def test_eliminar_la_cuenta_borra_sus_consentimientos(client: TestClient, db) -> None:
    registro = _register(client)
    r = client.request(
        "DELETE",
        "/auth/me",
        json={"password": PASSWORD},
        headers=auth(registro["access_token"]),
    )
    assert r.status_code == 204, r.text
    quedan = db.execute(
        text("SELECT count(*) FROM user_consents WHERE user_id = :u"),
        {"u": registro["user"]["id"]},
    ).scalar_one()
    assert quedan == 0
