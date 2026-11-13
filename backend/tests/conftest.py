"""Raiz de tests.

A proposito NO define fixtures de base de datos: `tests/engine/` debe poder
correr sin infraestructura (requisito de la skill `motor-estadistico-testing`).
Todo lo que necesita PostgreSQL vive en `tests/api/conftest.py`.
"""

import os

# La API no arranca sin una clave de JWT propia (`config.check_secrets`), y el
# CI no tiene `.env`. Los tests usan siempre esta, no la del `.env` local.
os.environ.setdefault("JWT_SECRET_KEY", "clave-solo-para-los-tests-de-pytest-0123456789")
# Igual con la clave del administrador sembrado: la del `.env` local puede ser
# la de ejemplo, que tampoco deja arrancar la API.
os.environ.setdefault("SEED_ADMIN_PASSWORD", "clave-del-admin-de-pytest-456")
