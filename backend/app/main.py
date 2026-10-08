"""Punto de entrada de la API de Sebasanalisis."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    admin,
    admin_legal,
    admin_users,
    auth,
    bankroll,
    bets,
    games,
    legal,
    recommendations,
    sessions,
    suggestions,
)
from app.core.config import get_settings
from app.core.monitoring import init_monitoring

settings = get_settings()

# uvicorn solo configura sus propios loggers. Sin un handler para "app", lo que
# la aplicacion registra en INFO no sale por ningun lado: ni el correo que
# imprime EMAIL_BACKEND=console en desarrollo, ni un fallo de envio.
_app_logger = logging.getLogger("app")
if not _app_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s - %(message)s"))
    _app_logger.addHandler(_handler)
    _app_logger.setLevel(logging.INFO)

# Antes de crear la app: asi el monitoreo engancha sus rutas y sus errores.
init_monitoring(settings.sentry_dsn)

app = FastAPI(title=settings.app_name, version="0.1.0")

# Sin esto el frontend en otro puerto no puede llamar la API: el navegador
# bloquea la peticion antes de que salga. Los tests con TestClient corren en
# proceso y no lo detectan.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(games.router)
app.include_router(sessions.router)
app.include_router(suggestions.router)
app.include_router(recommendations.router)
app.include_router(bankroll.router)
app.include_router(bets.router)
app.include_router(admin.router)
app.include_router(admin_legal.router)
app.include_router(admin_users.router)
app.include_router(legal.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
