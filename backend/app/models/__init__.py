"""Registro unico de modelos: Alembic autogenera contra `Base.metadata`."""

from app.models.base import Base
from app.models.bet import Bet
from app.models.game import Game, GameVariant
from app.models.game_session import GameSession
from app.models.performance import SessionPerformance
from app.models.spin import Spin
from app.models.suggestion import BankrollSuggestion, StatisticalSuggestion
from app.models.user import PaymentEvent, Subscription, User

__all__ = [
    "Base",
    "Bet",
    "Game",
    "GameVariant",
    "GameSession",
    "PaymentEvent",
    "SessionPerformance",
    "Spin",
    "StatisticalSuggestion",
    "BankrollSuggestion",
    "Subscription",
    "User",
]
