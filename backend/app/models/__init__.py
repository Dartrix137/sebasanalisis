"""Registro unico de modelos: Alembic autogenera contra `Base.metadata`."""

from app.models.audit import AdminAuditLog
from app.models.base import Base
from app.models.bet import Bet
from app.models.billing import Coupon, CouponPlan, CouponRedemption, Plan
from app.models.game import Game, GameVariant
from app.models.game_session import GameSession
from app.models.legal import LegalDocument, UserConsent
from app.models.performance import SessionPerformance
from app.models.spin import Spin
from app.models.suggestion import BankrollSuggestion, StatisticalSuggestion
from app.models.user import PaymentEvent, Subscription, User
from app.models.user_token import UserToken

__all__ = [
    "AdminAuditLog",
    "Base",
    "Bet",
    "Coupon",
    "CouponPlan",
    "CouponRedemption",
    "Game",
    "GameVariant",
    "GameSession",
    "LegalDocument",
    "PaymentEvent",
    "Plan",
    "SessionPerformance",
    "Spin",
    "StatisticalSuggestion",
    "BankrollSuggestion",
    "Subscription",
    "User",
    "UserConsent",
    "UserToken",
]
