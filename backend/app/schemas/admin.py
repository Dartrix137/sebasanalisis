"""
Schemas: administracion de usuarios, suscripciones, pagos y bitacora (§4.2, §4.3 y §4.6
de la Fase 4)
"""
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.auth import AccessType, UserResponse, UserRole
from app.schemas.base import ApiModel, Reason
from app.schemas.billing import (
    AdminPaymentResponse,
    CreditNoteStatus,
    InvoiceStatus,
    SubscriptionResponse,
)
from app.schemas.legal import ConsentResponse


class SubscriptionFilter(str, Enum):
    """Filtro de `GET /admin/users` por la suscripcion de la cuenta.

    No es `subscriptions.status` tal cual: lo que el administrador necesita
    saber es si el periodo pagado sigue vigente, y eso depende de la fecha.
    """
    #: Con un periodo pagado que todavia no vence.
    in_force = "in_force"
    #: Pago alguna vez y el periodo ya vencio.
    lapsed = "lapsed"
    #: Abrio un pago y nunca lo completo.
    pending = "pending"
    #: Nunca abrio un pago.
    none = "none"


class AdminUserListResponse(ApiModel):
    items: list[UserResponse]
    # Cuantas cuentas cumplen el filtro, no cuantas vienen en esta pagina.
    total: int
    limit: int
    offset: int


class UpdateUserAccessRequest(ApiModel):
    """PATCH /admin/users/:id/access: otorga o retira el acceso manual."""
    access_type: AccessType
    # Solo con `invited`. Null = sin vencimiento.
    access_expires_at: datetime | None = None
    reason: Reason


class UpdateUserStatusRequest(ApiModel):
    """PATCH /admin/users/:id/status: suspende o reactiva la cuenta."""
    is_active: bool
    reason: Reason


class UpdateUserRoleRequest(ApiModel):
    """PATCH /admin/users/:id/role: nombra un administrador o le quita el rol."""
    role: UserRole
    reason: Reason


class AuditLogEntry(ApiModel):
    id: UUID
    admin_user_id: UUID | None = None
    admin_email: str
    action: str
    target_type: str
    target_id: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    reason: str | None = None
    ip: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLogListResponse(ApiModel):
    items: list[AuditLogEntry]
    total: int
    limit: int
    offset: int


class AdminUserDetailResponse(ApiModel):
    """Una cuenta vista por el administrador (§4.2).

    Las acciones sobre la suscripcion son las de `PATCH /admin/subscriptions/:id`
    y las de un pago, las de `/admin/payments/:id` (§4.3).
    """
    user: UserResponse
    # La que tiene un periodo pagado, vigente o no. Null si nunca pago.
    subscription: SubscriptionResponse | None = None
    # Los ultimos intentos de cobro, incluidos los que no se completaron.
    payments: list[AdminPaymentResponse]
    consents: list[ConsentResponse]
    sessions_count: int
    # Lo que los administradores han hecho sobre esta cuenta, lo mas reciente primero.
    audit: list[AuditLogEntry]


# ---------- Suscripciones y pagos (§4.3, paso 6) ----------

class AdminSubscriptionResponse(SubscriptionResponse):
    """Una suscripcion vista por el administrador."""
    # La pasarela de la suscripcion. Las de `wompi` son del sandbox (paso 5.1).
    provider: str
    user_id: UUID
    user_email: str
    # Intentos de cobro fallidos del periodo en curso (renovacion automatica).
    retry_count: int
    canceled_at: datetime | None = None
    created_at: datetime


class AdminSubscriptionListResponse(ApiModel):
    items: list[AdminSubscriptionResponse]
    total: int
    limit: int
    offset: int


class AdminSubscriptionDetailResponse(ApiModel):
    subscription: AdminSubscriptionResponse
    # Los pagos de esta suscripcion, lo mas reciente primero.
    payments: list[AdminPaymentResponse]
    # Lo que los administradores han hecho sobre ella, lo mas reciente primero.
    audit: list[AuditLogEntry]


class SubscriptionAdminAction(str, Enum):
    #: Corre `current_period_end` unos dias, sin cobrar (compensacion).
    extend = "extend"
    #: Detiene la renovacion automatica; el acceso sigue hasta el vencimiento.
    cancel_at_period_end = "cancel_at_period_end"
    #: Termina el periodo ahora: el acceso cae en el acto. No devuelve nada.
    cancel_now = "cancel_now"


class UpdateSubscriptionRequest(ApiModel):
    """PATCH /admin/subscriptions/:id."""
    action: SubscriptionAdminAction
    # Solo con `extend`.
    days: int | None = Field(default=None, ge=1, le=90)
    reason: Reason


class PaymentEventResponse(ApiModel):
    """Un evento del proveedor de pagos, como llego."""
    id: UUID
    provider_event_id: str
    event_type: str | None = None
    status: str
    signature_verified: bool
    processed_at: datetime | None = None
    created_at: datetime
    # False: no quedo asociado al pago (por ejemplo, firma invalida) y se
    # muestra porque su cuerpo nombra la transaccion o la referencia del pago.
    linked: bool
    raw_payload: dict[str, Any] | None = None


class PaymentRefundResponse(ApiModel):
    """Un reembolso hecho en el panel del proveedor y registrado aqui."""
    id: UUID
    amount_cents: int
    currency: str
    refunded_at: datetime
    provider_refund_id: str | None = None
    reason: str
    admin_email: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminPaymentListResponse(ApiModel):
    items: list[AdminPaymentResponse]
    total: int
    limit: int
    offset: int


class InvoiceResponse(ApiModel):
    """La factura electronica de un pago aprobado (§3.17; pasos 5.2 y 5.4)."""
    status: InvoiceStatus
    # El dia de la aprobacion del pago, en hora de Colombia.
    operation_date: date
    created_at: datetime
    # Por que todavia no sale (`billing_profile_missing`, `rates_pending`...).
    waiting_reason: str | None = None
    attempts: int = 0
    next_attempt_at: datetime | None = None
    # Lo congelado: el monto en pesos y las tasas, como texto para no perder
    # decimales.
    prepared_at: datetime | None = None
    cop_cents: int | None = None
    eur_usd: str | None = None
    eur_usd_date: date | None = None
    eur_usd_source: str | None = None
    usd_cop: str | None = None
    usd_cop_date: date | None = None
    usd_cop_source: str | None = None
    # A quien va (la copia congelada).
    buyer_name: str | None = None
    buyer_id_type: str | None = None
    buyer_id_number: str | None = None
    # La emision.
    issue_date: date | None = None
    provider_name: str | None = None
    stamp_status: str | None = None
    cufe: str | None = None
    mail_status: str | None = None
    last_error_codes: list[str] | None = None
    last_error_message: str | None = None
    dian_errors: list[str] | None = None
    accepted_at: datetime | None = None
    # Por que no se emite (`cancelled`): `refunded`, `voided` o
    # `annulled_in_siigo`.
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None


class CreditNoteResponse(ApiModel):
    """Una nota credito de la factura (§3.17, "Paso 5.4", punto 12)."""
    id: UUID
    status: CreditNoteStatus
    # El motivo de la DIAN: 2 anulacion de la factura, 1 devolucion parcial.
    reason: int
    # Lo devuelto, en la moneda del pago.
    amount_cents: int
    currency: str
    # El reembolso que la origino; null si fue una anulacion de la pasarela.
    refund_id: UUID | None = None
    created_at: datetime
    # Por que todavia no sale (`invoice_not_accepted`, `credit_note_type_missing`).
    waiting_reason: str | None = None
    attempts: int = 0
    next_attempt_at: datetime | None = None
    # El valor en pesos, con las tasas de la factura.
    cop_cents: int | None = None
    issue_date: date | None = None
    provider_name: str | None = None
    stamp_status: str | None = None
    cude: str | None = None
    mail_status: str | None = None
    last_error_codes: list[str] | None = None
    last_error_message: str | None = None
    accepted_at: datetime | None = None
    cancelled_at: datetime | None = None


class AdminPaymentDetailResponse(ApiModel):
    payment: AdminPaymentResponse
    # Null mientras el pago no este aprobado.
    invoice: InvoiceResponse | None = None
    # Si la emision de facturas esta encendida (INVOICE_ISSUER).
    invoice_issuer_enabled: bool = False
    # Las notas credito de la factura, en orden de creacion.
    credit_notes: list[CreditNoteResponse] = []
    # Lo que llego del proveedor sobre este pago, en orden de llegada.
    events: list[PaymentEventResponse]
    refunds: list[PaymentRefundResponse]
    audit: list[AuditLogEntry]


class RequeryPaymentRequest(ApiModel):
    """POST /admin/payments/:id/requery."""
    reason: Reason


class InvoiceActionRequest(ApiModel):
    """POST /admin/payments/:id/invoice/retry, /refresh y /cancel, y
    /admin/payments/:id/credit-notes/:id/retry y /refresh."""
    reason: Reason


class RecordRefundRequest(ApiModel):
    """POST /admin/payments/:id/refunds. La moneda es la del pago."""
    amount_cents: int = Field(gt=0, le=2_147_483_647)
    # Cuando se hizo en el panel del proveedor.
    refunded_at: datetime
    provider_refund_id: str | None = Field(default=None, max_length=255)
    reason: Reason


class ForcePasswordResetRequest(ApiModel):
    """POST /admin/users/:id/force-password-reset."""
    reason: Reason


# ---------- Resumen (§4.7, paso 6) ----------

class OverviewPeriod(ApiModel):
    """Las dos ventanas que se comparan: [start, end). Mes calendario en hora
    de Bogota hasta ahora, y el mismo tramo del mes anterior."""
    current_start: datetime
    current_end: datetime
    previous_start: datetime
    previous_end: datetime
    timezone: str


class Comparison(ApiModel):
    """Un indicador de flujo en el mes en curso y en el mismo tramo del anterior."""
    current: int
    previous: int


class MoneyComparison(ApiModel):
    currency: str
    current_cents: int
    previous_cents: int


class RateComparison(ApiModel):
    """Una tasa en puntos basicos (1 % = 100). Null si no hay base."""
    current_bp: int | None = None
    previous_bp: int | None = None


class SubscriptionCounts(ApiModel):
    """Cuantas suscripciones hay hoy en cada estado, tal como estan en la base."""
    pending: int
    active: int
    past_due: int
    canceled: int
    expired: int
    # Con el periodo pagado vigente (activas, canceladas y en mora).
    in_force: int


class RecurringRevenue(ApiModel):
    """Ingreso recurrente mensual de una moneda, hoy."""
    currency: str
    total_cents: int
    automatic_cents: int
    manual_cents: int
    subscriptions: int


class AdminOverviewResponse(ApiModel):
    period: OverviewPeriod
    # Fotos del momento: no se comparan.
    subscriptions: SubscriptionCounts
    recurring: list[RecurringRevenue]
    # Flujos del periodo.
    new_subscriptions: Comparison
    cancellations: Comparison
    cancellation_rate: RateComparison
    failed_charges: Comparison
    registrations: Comparison
    verified_registrations: Comparison
    collected: list[MoneyComparison]
