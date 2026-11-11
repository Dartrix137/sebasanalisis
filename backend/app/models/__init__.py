"""Registro unico de modelos: Alembic autogenera contra `Base.metadata`."""

from app.models.audit import AdminAuditLog
from app.models.base import Base
from app.models.bet import Bet
from app.models.billing import (
    BillingProfile,
    Coupon,
    CouponPlan,
    CouponRedemption,
    CreditNote,
    ExchangeRate,
    Invoice,
    Plan,
    PriceChange,
    SubscriptionPriceChange,
)
from app.models.game import Game, GameVariant, PlanGame
from app.models.game_session import GameSession
from app.models.legal import LegalDocument, LegalNotice, UserConsent
from app.models.performance import SessionPerformance
from app.models.spin import Spin
from app.models.suggestion import BankrollSuggestion, StatisticalSuggestion
from app.models.user import Payment, PaymentEvent, PaymentRefund, Subscription, User
from app.models.user_token import UserToken

__all__ = [
    "AdminAuditLog",
    "Base",
    "BillingProfile",
    "Bet",
    "Coupon",
    "CouponPlan",
    "CouponRedemption",
    "CreditNote",
    "ExchangeRate",
    "Game",
    "GameVariant",
    "GameSession",
    "Invoice",
    "LegalDocument",
    "LegalNotice",
    "Payment",
    "PaymentEvent",
    "PaymentRefund",
    "Plan",
    "PlanGame",
    "PriceChange",
    "SessionPerformance",
    "Spin",
    "StatisticalSuggestion",
    "BankrollSuggestion",
    "Subscription",
    "SubscriptionPriceChange",
    "User",
    "UserConsent",
    "UserToken",
]
