"""Modelo de acceso y bitacora de auditoria (§2 y §4.6 de la Fase 4).

Los tests de aceptacion de §2.4, mas el acceso manual desde el admin. Las
cuentas de estos tests se registran con `register_raw`, que las deja como las
deja el registro real: sin acceso. (El `client.post` de los demas tests les da
acceso solo; ver `conftest.register_with_consents`.)
"""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.access import has_access
from app.models import User
from tests.api.conftest import OPEN_PREFIXES, auth, register_raw

PASSWORD = "clave-segura-123"
MOTIVO = "Prueba de acceso manual"


def _email() -> str:
    return f"acceso-{uuid.uuid4().hex[:12]}@ejemplo.com"


def _sin_acceso(client: TestClient) -> dict:
    return register_raw(client, _email(), PASSWORD)


def _me(client: TestClient, token: str) -> dict:
    r = client.get("/auth/me", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _set(db, user_id: str, **campos) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in campos)
    db.execute(text(f"UPDATE users SET {sets} WHERE id = :id"), {**campos, "id": user_id})
    db.commit()


def _suscripcion(db, user_id: str, status: str, period_end: datetime) -> None:
    db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, provider, status, current_period_end) "
            "VALUES (:id, :u, 'wompi', :s, :e)"
        ),
        {"id": str(uuid.uuid4()), "u": user_id, "s": status, "e": period_end},
    )
    db.commit()


def _denegado(client: TestClient, token: str, code: str) -> None:
    r = client.get("/sessions", headers=auth(token))
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == code


def _permitido(client: TestClient, token: str) -> None:
    assert client.get("/sessions", headers=auth(token)).status_code == 200


# ---------- §2.4: tests de aceptacion ----------


def test_cuenta_nueva_no_tiene_acceso(client: TestClient) -> None:
    registro = _sin_acceso(client)
    token = registro["access_token"]
    assert registro["user"]["access_type"] == "none"
    assert registro["user"]["access"] == {"granted": False, "reason": "no_access", "until": None}

    r = client.post("/sessions", json={}, headers=auth(token))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "no_access"

    # La cuenta no queda bloqueada: perfil, documentos y exportacion siguen.
    assert _me(client, token)["access"]["reason"] == "no_access"
    assert client.get("/legal/consents", headers=auth(token)).status_code == 200
    assert client.get("/auth/me/export", headers=auth(token)).status_code == 200


def test_invitado_con_vencimiento_pasado_esta_vencido(client: TestClient, db) -> None:
    registro = _sin_acceso(client)
    token, user_id = registro["access_token"], registro["user"]["id"]
    ayer = datetime.now(UTC) - timedelta(days=1)

    _set(db, user_id, access_type="invited", access_expires_at=ayer)
    _denegado(client, token, "expired")
    access = _me(client, token)["access"]
    assert (access["granted"], access["reason"]) == (False, "expired")
    assert access["until"] is not None

    # Con el vencimiento en el futuro, o sin vencimiento, entra.
    _set(db, user_id, access_expires_at=datetime.now(UTC) + timedelta(days=1))
    _permitido(client, token)
    access = _me(client, token)["access"]
    assert (access["granted"], access["reason"]) == (True, "invited")
    assert access["until"] is not None

    _set(db, user_id, access_expires_at=None)
    _permitido(client, token)
    assert _me(client, token)["access"] == {"granted": True, "reason": "invited", "until": None}


def test_cuenta_suspendida_con_suscripcion_activa_no_tiene_acceso(client: TestClient, db) -> None:
    registro = _sin_acceso(client)
    token, user_id = registro["access_token"], registro["user"]["id"]
    _suscripcion(db, user_id, "active", datetime.now(UTC) + timedelta(days=20))
    _permitido(client, token)
    assert _me(client, token)["access"]["reason"] == "subscription"

    _set(db, user_id, is_active=False)
    _denegado(client, token, "suspended")
    # Suspendida no es expulsada: sigue entrando a su cuenta.
    assert _me(client, token)["access"]["reason"] == "suspended"
    assert client.post(
        "/auth/login", json={"email": registro["user"]["email"], "password": PASSWORD}
    ).status_code == 200


@pytest.mark.parametrize("status", ["active", "canceled"])
def test_suscripcion_da_acceso_solo_mientras_dura_el_periodo(
    client: TestClient, db, status: str
) -> None:
    """`canceled` cuenta: la cancelacion es al final del periodo pagado (§3.6)."""
    registro = _sin_acceso(client)
    token, user_id = registro["access_token"], registro["user"]["id"]

    _suscripcion(db, user_id, status, datetime.now(UTC) + timedelta(days=3))
    _permitido(client, token)
    access = _me(client, token)["access"]
    assert (access["granted"], access["reason"]) == (True, "subscription")
    assert access["until"] is not None

    # Con el periodo en el pasado, el acceso queda revocado.
    db.execute(
        text("UPDATE subscriptions SET current_period_end = :e WHERE user_id = :u"),
        {"e": datetime.now(UTC) - timedelta(minutes=1), "u": user_id},
    )
    db.commit()
    _denegado(client, token, "expired")


@pytest.mark.parametrize("status", ["pending", "past_due_sin_periodo", "expired"])
def test_suscripcion_en_otro_estado_no_da_acceso(client: TestClient, db, status: str) -> None:
    registro = _sin_acceso(client)
    _suscripcion(db, registro["user"]["id"], status, datetime.now(UTC) + timedelta(days=3))
    _denegado(client, registro["access_token"], "no_access")


def test_admin_siempre_accede_aunque_no_tenga_suscripcion(client: TestClient, db) -> None:
    registro = _sin_acceso(client)
    token, user_id = registro["access_token"], registro["user"]["id"]
    _denegado(client, token, "no_access")

    _set(db, user_id, role="admin")
    _permitido(client, token)
    assert _me(client, token)["access"] == {"granted": True, "reason": "admin", "until": None}


def test_acceso_full_no_vence(client: TestClient, db) -> None:
    registro = _sin_acceso(client)
    _set(db, registro["user"]["id"], access_type="full")
    _permitido(client, registro["access_token"])
    assert _me(client, registro["access_token"])["access"]["reason"] == "full"


def test_todos_los_routers_de_juego_rechazan_una_cuenta_sin_acceso(client: TestClient) -> None:
    """Recorre TODAS las rutas de juego con una cuenta sin acceso. Un router
    nuevo que olvide `RequireAccess` rompe este test en vez de quedar abierto."""
    from app.main import app

    token = _sin_acceso(client)["access_token"]

    probadas = 0
    for ruta, operaciones in app.openapi()["paths"].items():
        if ruta.startswith(OPEN_PREFIXES):
            continue
        path = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), ruta)
        for method in operaciones:
            r = client.request(method.upper(), path, headers=auth(token))
            assert r.status_code == 403, f"{method} {ruta} respondió {r.status_code}"
            assert r.json()["detail"]["code"] == "no_access", f"{method} {ruta}"
            probadas += 1
    # Si la cuenta baja, alguien movio las rutas de juego a un prefijo "abierto".
    assert probadas >= 25


def test_has_access_sigue_el_orden_de_las_reglas(client: TestClient, db) -> None:
    """§2.2: suspendida gana a todo; el consentimiento va antes que el rol."""
    registro = _sin_acceso(client)
    user_id = registro["user"]["id"]
    now = datetime.now(UTC)

    def decide() -> tuple[bool, str]:
        db.expire_all()
        d = has_access(db, db.get(User, uuid.UUID(user_id)), now)
        return d.granted, d.reason

    assert decide() == (False, "no_access")

    _set(db, user_id, role="admin", access_type="full")
    assert decide() == (True, "admin")

    # Sin la mayoria de edad declarada, ni el administrador entra.
    _set(db, user_id, adult_confirmed_at=None)
    assert decide() == (False, "consent_required")

    # Y suspendida, el motivo es ese aunque tambien le falte el consentimiento.
    _set(db, user_id, is_active=False)
    assert decide() == (False, "suspended")


# ---------- Acceso manual desde el admin ----------


def test_admin_otorga_y_retira_acceso_y_queda_en_la_bitacora(
    client: TestClient, admin_token: str, db
) -> None:
    registro = _sin_acceso(client)
    token, user_id = registro["access_token"], registro["user"]["id"]
    vence = (datetime.now(UTC) + timedelta(days=30)).isoformat()

    r = client.patch(
        f"/admin/users/{user_id}/access",
        json={"access_type": "invited", "access_expires_at": vence, "reason": MOTIVO},
        headers=auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_type"] == "invited"
    assert r.json()["access"]["reason"] == "invited"
    _permitido(client, token)

    r = client.patch(
        f"/admin/users/{user_id}/access",
        json={"access_type": "none", "reason": "Se retira la cortesía"},
        headers=auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_expires_at"] is None
    _denegado(client, token, "no_access")

    filas = db.execute(
        text(
            "SELECT action, before, after, reason, admin_email, ip FROM admin_audit_log "
            "WHERE target_type = 'user' AND target_id = :u ORDER BY created_at"
        ),
        {"u": user_id},
    ).all()
    assert [f.action for f in filas] == ["user.access.update", "user.access.update"]
    assert filas[0].before == {"access_type": "none", "access_expires_at": None}
    assert filas[0].after["access_type"] == "invited"
    assert filas[0].after["access_expires_at"] is not None
    assert filas[0].reason == MOTIVO
    assert filas[0].admin_email.startswith("admin-")
    assert filas[0].ip == "testclient"
    assert filas[1].before["access_type"] == "invited"
    assert filas[1].after == {"access_type": "none", "access_expires_at": None}


@pytest.mark.parametrize(
    "body",
    [
        {"access_type": "invited"},  # sin motivo
        {"access_type": "invited", "reason": "  "},  # motivo vacio
        {"access_type": "premium", "reason": MOTIVO},
        {"access_type": "trial", "reason": MOTIVO},  # ya no existe
        # El vencimiento solo aplica a `invited`, y tiene que ser futuro.
        {"access_type": "full", "access_expires_at": "2099-01-01T00:00:00Z", "reason": MOTIVO},
        {"access_type": "invited", "access_expires_at": "2020-01-01T00:00:00Z", "reason": MOTIVO},
    ],
)
def test_cambio_de_acceso_invalido_no_cambia_nada_ni_deja_bitacora(
    client: TestClient, admin_token: str, db, body: dict
) -> None:
    user_id = _sin_acceso(client)["user"]["id"]
    r = client.patch(f"/admin/users/{user_id}/access", json=body, headers=auth(admin_token))
    assert r.status_code == 422, r.text
    assert (
        db.execute(text("SELECT access_type FROM users WHERE id = :u"), {"u": user_id}).scalar_one()
        == "none"
    )
    assert (
        db.execute(
            text("SELECT count(*) FROM admin_audit_log WHERE target_id = :u"), {"u": user_id}
        ).scalar_one()
        == 0
    )


def test_un_cambio_que_no_cambia_nada_se_rechaza_y_no_deja_bitacora(
    client: TestClient, admin_token: str, db
) -> None:
    user_id = _sin_acceso(client)["user"]["id"]
    h = auth(admin_token)
    vence = (datetime.now(UTC) + timedelta(days=10)).isoformat()

    def acceso(**body):
        return client.patch(
            f"/admin/users/{user_id}/access", json={**body, "reason": MOTIVO}, headers=h
        )

    def estado(is_active: bool):
        return client.patch(
            f"/admin/users/{user_id}/status",
            json={"is_active": is_active, "reason": MOTIVO},
            headers=h,
        )

    # La cuenta nace sin acceso y activa: pedir eso mismo no cambia nada.
    assert acceso(access_type="none").status_code == 409
    assert estado(True).status_code == 409

    assert acceso(access_type="invited", access_expires_at=vence).status_code == 200
    r = acceso(access_type="invited", access_expires_at=vence)
    assert r.status_code == 409
    assert "no hay nada que cambiar" in r.json()["detail"]
    # Mismo tipo con otro vencimiento si es un cambio.
    assert acceso(access_type="invited").status_code == 200

    assert estado(False).status_code == 200
    r = estado(False)
    assert r.status_code == 409
    assert "ya está suspendida" in r.json()["detail"]

    acciones = db.execute(
        text("SELECT action FROM admin_audit_log WHERE target_id = :u ORDER BY created_at"),
        {"u": user_id},
    ).scalars().all()
    assert acciones == ["user.access.update", "user.access.update", "user.status.update"]


def test_el_acceso_manual_no_aplica_a_un_administrador(
    client: TestClient, admin_token: str, db
) -> None:
    """Entra por su rol: guardar el cambio no tendria efecto, asi que se rechaza."""
    yo = _me(client, admin_token)
    for access_type in ("none", "invited", "full"):
        r = client.patch(
            f"/admin/users/{yo['id']}/access",
            json={"access_type": access_type, "reason": MOTIVO},
            headers=auth(admin_token),
        )
        assert r.status_code == 409, r.text
        assert "por su rol" in r.json()["detail"]

    despues = _me(client, admin_token)
    assert despues["access_type"] == yo["access_type"]
    assert despues["access"]["reason"] == "admin"
    assert (
        db.execute(
            text("SELECT count(*) FROM admin_audit_log WHERE target_id = :u"), {"u": yo["id"]}
        ).scalar_one()
        == 0
    )


def test_admin_suspende_y_reactiva_una_cuenta(client: TestClient, admin_token: str, db) -> None:
    registro = _sin_acceso(client)
    token, user_id = registro["access_token"], registro["user"]["id"]
    _set(db, user_id, access_type="full")
    _permitido(client, token)

    r = client.patch(
        f"/admin/users/{user_id}/status",
        json={"is_active": False, "reason": "Uso indebido de la cuenta"},
        headers=auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False
    assert r.json()["access"]["reason"] == "suspended"
    _denegado(client, token, "suspended")

    r = client.patch(
        f"/admin/users/{user_id}/status",
        json={"is_active": True, "reason": "Se aclaró el caso"},
        headers=auth(admin_token),
    )
    assert r.status_code == 200
    _permitido(client, token)

    acciones = db.execute(
        text(
            "SELECT action, after FROM admin_audit_log WHERE target_id = :u ORDER BY created_at"
        ),
        {"u": user_id},
    ).all()
    assert [(a.action, a.after) for a in acciones] == [
        ("user.status.update", {"is_active": False}),
        ("user.status.update", {"is_active": True}),
    ]


def test_un_admin_no_puede_suspenderse(client: TestClient, admin_token: str) -> None:
    yo = _me(client, admin_token)["id"]
    r = client.patch(
        f"/admin/users/{yo}/status",
        json={"is_active": False, "reason": MOTIVO},
        headers=auth(admin_token),
    )
    assert r.status_code == 409
    assert _me(client, admin_token)["is_active"] is True


def test_un_admin_suspendido_deja_de_administrar(client: TestClient, admin_token: str, db) -> None:
    yo = _me(client, admin_token)["id"]
    _set(db, yo, is_active=False)
    assert client.get("/admin/users", headers=auth(admin_token)).status_code == 403
    assert client.get("/admin/audit-log", headers=auth(admin_token)).status_code == 403
    assert client.get("/admin/legal-documents", headers=auth(admin_token)).status_code == 403


def test_los_endpoints_de_usuarios_son_solo_para_administradores(
    client: TestClient, user_token: str
) -> None:
    otro = _sin_acceso(client)["user"]["id"]
    h = auth(user_token)
    assert client.get("/admin/users", headers=h).status_code == 403
    assert client.get(f"/admin/users/{otro}", headers=h).status_code == 403
    assert client.get("/admin/audit-log", headers=h).status_code == 403
    r = client.patch(
        f"/admin/users/{otro}/access", json={"access_type": "full", "reason": MOTIVO}, headers=h
    )
    assert r.status_code == 403
    r = client.patch(
        f"/admin/users/{otro}/status", json={"is_active": False, "reason": MOTIVO}, headers=h
    )
    assert r.status_code == 403
    assert client.get("/admin/users").status_code == 401
    # Y nada de eso cambio la cuenta.
    assert _me(client, user_token)["access_type"] == "invited"


def test_usuario_inexistente_es_404(client: TestClient, admin_token: str) -> None:
    fantasma = uuid.uuid4()
    h = auth(admin_token)
    assert client.get(f"/admin/users/{fantasma}", headers=h).status_code == 404
    r = client.patch(
        f"/admin/users/{fantasma}/access", json={"access_type": "full", "reason": MOTIVO}, headers=h
    )
    assert r.status_code == 404


# ---------- Rol ----------


def _rol(client: TestClient, token: str, user_id: str, role: str, reason: str | None = MOTIVO):
    body = {"role": role} if reason is None else {"role": role, "reason": reason}
    return client.patch(f"/admin/users/{user_id}/role", json=body, headers=auth(token))


def test_admin_nombra_otro_administrador_y_le_quita_el_rol(
    client: TestClient, admin_token: str, db
) -> None:
    registro = _sin_acceso(client)
    token, user_id = registro["access_token"], registro["user"]["id"]
    assert client.get("/admin/users", headers=auth(token)).status_code == 403

    r = _rol(client, admin_token, user_id, "admin")
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"
    assert r.json()["access"]["reason"] == "admin"
    # Ya administra y entra a la mesa por su rol, sin acceso manual.
    assert client.get("/admin/users", headers=auth(token)).status_code == 200
    _permitido(client, token)
    # Y con dos administradores activos, el primero ya puede eliminar su cuenta.
    assert _me(client, admin_token)["can_delete_account"] is True

    r = _rol(client, admin_token, user_id, "user", "Deja el equipo")
    assert r.status_code == 200, r.text
    # Sin el rol vuelve a depender de su acceso manual, que seguia en `none`.
    assert r.json()["access"]["reason"] == "no_access"
    assert client.get("/admin/users", headers=auth(token)).status_code == 403
    _denegado(client, token, "no_access")

    filas = db.execute(
        text(
            "SELECT action, before, after, reason FROM admin_audit_log "
            "WHERE target_id = :u ORDER BY created_at"
        ),
        {"u": user_id},
    ).all()
    assert [(f.action, f.before, f.after, f.reason) for f in filas] == [
        ("user.role.update", {"role": "user"}, {"role": "admin"}, MOTIVO),
        ("user.role.update", {"role": "admin"}, {"role": "user"}, "Deja el equipo"),
    ]


def test_cambios_de_rol_que_se_rechazan(client: TestClient, admin_token: str, db) -> None:
    yo = _me(client, admin_token)["id"]
    user_id = _sin_acceso(client)["user"]["id"]

    # Nadie se quita el rol a si mismo: siempre queda al menos un administrador.
    r = _rol(client, admin_token, yo, "user")
    assert r.status_code == 409
    assert "tu propio rol" in r.json()["detail"]
    assert _me(client, admin_token)["role"] == "admin"

    # Un cambio que no cambia nada.
    assert _rol(client, admin_token, user_id, "user").status_code == 409
    # Sin motivo, o con un rol que no existe.
    assert _rol(client, admin_token, user_id, "admin", reason=None).status_code == 422
    assert _rol(client, admin_token, user_id, "superadmin").status_code == 422
    assert _rol(client, admin_token, str(uuid.uuid4()), "admin").status_code == 404

    # Una cuenta suspendida no se nombra administradora.
    _set(db, user_id, is_active=False)
    r = _rol(client, admin_token, user_id, "admin")
    assert r.status_code == 409
    assert "suspendida" in r.json()["detail"]

    assert (
        db.execute(text("SELECT role FROM users WHERE id = :u"), {"u": user_id}).scalar_one()
        == "user"
    )
    assert (
        db.execute(
            text("SELECT count(*) FROM admin_audit_log WHERE target_id IN (:a, :b)"),
            {"a": user_id, "b": yo},
        ).scalar_one()
        == 0
    )


def test_solo_un_administrador_cambia_roles(client: TestClient, user_token: str) -> None:
    yo = _me(client, user_token)["id"]
    assert _rol(client, user_token, yo, "admin").status_code == 403
    assert client.patch(f"/admin/users/{yo}/role", json={"role": "admin", "reason": MOTIVO}).status_code == 401
    assert _me(client, user_token)["role"] == "user"


# ---------- Lista, busqueda y detalle ----------


def test_lista_de_usuarios_pagina_busca_y_filtra(client: TestClient, admin_token: str, db) -> None:
    marca = f"buscable{uuid.uuid4().hex[:10]}"
    ids = [register_raw(client, f"{marca}-{i}@ejemplo.com")["user"]["id"] for i in range(3)]
    _set(db, ids[0], access_type="full")
    _set(db, ids[1], is_active=False)
    h = auth(admin_token)

    r = client.get("/admin/users", params={"query": marca.upper()}, headers=h)
    assert r.status_code == 200, r.text
    pagina = r.json()
    assert pagina["total"] == 3
    assert {u["id"] for u in pagina["items"]} == set(ids)
    # Cada fila trae la misma decision que aplica la mesa.
    motivos = {u["id"]: u["access"]["reason"] for u in pagina["items"]}
    assert motivos == {ids[0]: "full", ids[1]: "suspended", ids[2]: "no_access"}

    # Paginacion: el total no cambia, las paginas no se repiten.
    uno = client.get("/admin/users", params={"query": marca, "limit": 2}, headers=h).json()
    dos = client.get(
        "/admin/users", params={"query": marca, "limit": 2, "offset": 2}, headers=h
    ).json()
    assert (uno["total"], len(uno["items"]), len(dos["items"])) == (3, 2, 1)
    assert {u["id"] for u in uno["items"]}.isdisjoint(u["id"] for u in dos["items"])

    def filtrados(**params) -> set[str]:
        r = client.get("/admin/users", params={"query": marca, **params}, headers=h)
        assert r.status_code == 200, r.text
        return {u["id"] for u in r.json()["items"]}

    assert filtrados(access_type="full") == {ids[0]}
    assert filtrados(access_type="none") == {ids[1], ids[2]}
    assert filtrados(is_active="false") == {ids[1]}
    assert filtrados(role="admin") == set()
    assert filtrados(email_verified="true") == set()

    # Un comodin escrito en la busqueda se busca literal: no trae todo.
    assert client.get("/admin/users", params={"query": "%"}, headers=h).json()["total"] == 0
    assert client.get("/admin/users", params={"limit": 500}, headers=h).status_code == 422


def test_detalle_de_usuario(client: TestClient, admin_token: str) -> None:
    registro = _sin_acceso(client)
    user_id = registro["user"]["id"]
    h = auth(admin_token)
    client.patch(
        f"/admin/users/{user_id}/access", json={"access_type": "full", "reason": MOTIVO}, headers=h
    )

    r = client.get(f"/admin/users/{user_id}", headers=h)
    assert r.status_code == 200, r.text
    detalle = r.json()
    assert detalle["user"]["email"] == registro["user"]["email"]
    assert detalle["user"]["access"]["reason"] == "full"
    assert {c["kind"] for c in detalle["consents"]} == {"terms", "privacy"}
    assert detalle["sessions_count"] == 0
    assert [a["action"] for a in detalle["audit"]] == ["user.access.update"]
    assert detalle["audit"][0]["reason"] == MOTIVO
    assert "password" not in r.text


# ---------- Bitacora ----------


def test_publicar_un_documento_legal_queda_en_la_bitacora(
    client: TestClient, admin_token: str
) -> None:
    h = auth(admin_token)
    r = client.post(
        "/admin/legal-documents",
        json={
            "kind": "cookies",
            "title": "Cookies",
            "content_md": "texto de prueba",
            "requires_acceptance": False,
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    documento = r.json()
    assert client.post(f"/admin/legal-documents/{documento['id']}/publish", headers=h).status_code == 200

    bitacora = client.get("/admin/audit-log", params={"limit": 5}, headers=h).json()
    assert bitacora["total"] >= 1
    ultima = bitacora["items"][0]
    assert ultima["action"] == "legal_document.publish"
    assert ultima["target_id"] == documento["id"]
    assert ultima["after"] == {
        "kind": "cookies",
        "version": documento["version"],
        "requires_acceptance": False,
    }


def test_la_bitacora_no_se_puede_borrar_ni_editar(client: TestClient, admin_token: str) -> None:
    h = auth(admin_token)
    assert client.delete("/admin/audit-log", headers=h).status_code == 405
    assert client.request("PATCH", "/admin/audit-log", json={}, headers=h).status_code == 405
    assert client.request("POST", "/admin/audit-log", json={}, headers=h).status_code == 405
