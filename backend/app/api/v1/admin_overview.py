"""Admin: resumen del negocio (docs/PLATAFORMA_COMPLETA.md §4.7 y §4.9).

Solo lectura. Todo lo calcula `core/overview`, con montos en centavos y la
moneda al lado.
"""

from datetime import UTC, datetime

from fastapi import APIRouter

from app.api.deps import AdminUser, DbSession
from app.core import overview
from app.schemas.admin import (
    AdminOverviewResponse,
    Comparison,
    MoneyComparison,
    OverviewPeriod,
    RateComparison,
    RecurringRevenue,
    SubscriptionCounts,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview", response_model=AdminOverviewResponse)
def get_overview(db: DbSession, admin: AdminUser) -> AdminOverviewResponse:
    now = datetime.now(UTC)
    windows = overview.periods(now)
    cur, prev = windows.current, windows.previous

    def compare(count) -> Comparison:  # type: ignore[no-untyped-def]
        return Comparison(current=count(db, cur), previous=count(db, prev))

    cancellations = compare(overview.cancellations)
    registered_now, verified_now = overview.registrations(db, cur)
    registered_before, verified_before = overview.registrations(db, prev)
    collected_now = overview.collected(db, cur)
    collected_before = overview.collected(db, prev)
    return AdminOverviewResponse(
        period=OverviewPeriod(
            current_start=cur.start,
            current_end=cur.end,
            previous_start=prev.start,
            previous_end=prev.end,
            timezone=str(overview.BOGOTA),
        ),
        subscriptions=SubscriptionCounts(
            **overview.subscriptions_by_status(db), in_force=overview.in_force_count(db, now)
        ),
        recurring=[
            RecurringRevenue(
                currency=r.currency,
                total_cents=r.total_cents,
                automatic_cents=r.automatic_cents,
                manual_cents=r.manual_cents,
                subscriptions=r.subscriptions,
            )
            for r in overview.recurring(db, now)
        ],
        new_subscriptions=compare(overview.new_subscriptions),
        cancellations=cancellations,
        # Canceladas en el periodo sobre las que estaban vigentes al empezar.
        cancellation_rate=RateComparison(
            current_bp=overview.rate_bp(cancellations.current, overview.in_force_at(db, cur.start)),
            previous_bp=overview.rate_bp(
                cancellations.previous, overview.in_force_at(db, prev.start)
            ),
        ),
        failed_charges=compare(overview.failed_charges),
        registrations=Comparison(current=registered_now, previous=registered_before),
        verified_registrations=Comparison(current=verified_now, previous=verified_before),
        collected=[
            MoneyComparison(
                currency=currency,
                current_cents=collected_now.get(currency, 0),
                previous_cents=collected_before.get(currency, 0),
            )
            for currency in sorted(set(collected_now) | set(collected_before))
        ],
    )
