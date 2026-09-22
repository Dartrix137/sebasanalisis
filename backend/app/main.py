"""Punto de entrada de la API de Sebasanalisis."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    admin,
    auth,
    bankroll,
    bets,
    games,
    recommendations,
    sessions,
    suggestions,
)
from app.core.config import get_settings

settings = get_settings()

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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
