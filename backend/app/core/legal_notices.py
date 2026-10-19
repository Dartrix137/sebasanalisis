"""Aviso por correo de una version nueva de un documento legal
(docs/PLATAFORMA_COMPLETA.md §6.7).

Publicar una version que exige aceptacion no basta para que alguien se entere:
la pantalla de aceptacion solo la ve quien vuelve a entrar a la mesa. Este
modulo le escribe a quien tiene algo en juego. Decidido por el usuario el
2026-10-19:

- **A quien**: a las cuentas con un periodo pagado vigente (suscripcion activa,
  en mora o cancelada con acceso), activas y con el correo verificado. No a las
  que entran con acceso manual sin suscripcion, ni a correos sin verificar.
- **Cuando**: al publicar. La version rige desde que se publica (como siempre)
  y el aviso sale en las corridas siguientes del job de renovaciones, por
  tandas.
- **De que**: de la ultima version de cada documento que exige aceptacion,
  siempre que reemplace a una version anterior publicada (la primera de un
  documento no "cambia" nada). Si la cuenta ya la acepto, no se le escribe.
  Si se publicaron dos versiones antes de que le llegara el aviso, recibe uno,
  de la ultima.
- **Un correo por cuenta**, aunque cambien los terminos y la politica de datos a
  la vez: lista los documentos y enlaza a su pagina publica.

La pantalla de aceptacion no cambia: es la que deja la constancia. El correo
solo avisa.

**Idempotencia**: la fila de `legal_notices` se escribe solo si el correo salio,
con una restriccion unica por (cuenta, version). El job corre con el candado de
Postgres de las renovaciones, asi que dos corridas no avisan a la misma cuenta a
la vez. Queda una ventana minima: si el proceso muere entre enviar y anotar, esa
cuenta recibe el aviso otra vez en la corrida siguiente (igual que los avisos de
un traslado de precio).

**Tope**: `NOTICES_PER_RUN` por corrida y, por dia (UTC), la mitad de
`EMAIL_DAILY_LIMIT`, contada en la base: el contador de `CappedEmailSender` vive
en memoria y no se comparte entre la API y el job. La otra mitad queda para los
correos de todos los dias (verificaciones, recibos, avisos de cobro).
"""

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.email import EmailMessage, EmailSender
from app.emails import build_email
from app.models import LegalDocument, LegalNotice, Subscription, User, UserConsent
from app.models.legal import LEGAL_KINDS

logger = logging.getLogger(__name__)

#: Cuantos avisos envia una corrida del job, como mucho. Corre cada hora.
NOTICES_PER_RUN = 40

#: Las suscripciones con un periodo pagado: las canceladas conservan el acceso
#: hasta `current_period_end`.
_PAID = ("active", "past_due", "canceled")

#: La pagina publica de cada documento. Es la misma tabla de
#: `frontend/lib/legal.ts`: si una cambia, cambia la otra.
PUBLIC_PATHS = {
    "terms": "/legal/terminos",
    "privacy": "/legal/privacidad",
    "refunds": "/legal/reembolsos",
    "cookies": "/legal/cookies",
}


@dataclass
class NoticeReport:
    sent: int = 0
    failed: int = 0
    #: Cuentas que quedaron para otra corrida por el tope del dia.
    deferred_by_daily_limit: bool = False
    recipients: list[str] = field(default_factory=list)


def batch_size(per_run: int, daily_limit: int, sent_today: int) -> int:
    """Cuantos avisos puede enviar esta corrida. `daily_limit` 0 = sin tope diario."""
    if daily_limit <= 0:
        return per_run
    return max(0, min(per_run, daily_limit - sent_today))


def notice_daily_limit() -> int:
    """La mitad de `EMAIL_DAILY_LIMIT`; 0 si no hay tope de correos."""
    return get_settings().email_daily_limit // 2


def notifiable_documents(db: Session) -> list[LegalDocument]:
    """Por tipo, la ultima version publicada que exige aceptacion, si reemplaza
    a una version anterior ya publicada."""
    latest_required = dict(
        db.execute(
            select(LegalDocument.kind, func.max(LegalDocument.version))
            .where(
                LegalDocument.published_at.is_not(None),
                LegalDocument.requires_acceptance.is_(True),
            )
            .group_by(LegalDocument.kind)
        ).all()
    )
    documents: list[LegalDocument] = []
    for kind, version in latest_required.items():
        earlier = db.scalar(
            select(func.count())
            .select_from(LegalDocument)
            .where(
                LegalDocument.kind == kind,
                LegalDocument.published_at.is_not(None),
                LegalDocument.version < version,
            )
        )
        if not earlier:
            continue
        document = db.scalar(
            select(LegalDocument).where(
                LegalDocument.kind == kind, LegalDocument.version == version
            )
        )
        if document is not None:
            documents.append(document)
    # Terminos primero, como en la pantalla de aceptacion.
    return sorted(documents, key=lambda doc: LEGAL_KINDS.index(doc.kind))


def _sent_today(db: Session, now: datetime) -> int:
    """Correos de aviso enviados hoy (UTC). Un correo que avisa de dos
    documentos deja dos filas con el mismo `sent_at`: cuenta como uno."""
    start = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    sent = (
        select(LegalNotice.user_id, LegalNotice.sent_at)
        .where(LegalNotice.sent_at >= start)
        .distinct()
        .subquery()
    )
    return db.scalar(select(func.count()).select_from(sent)) or 0


def _recipients(db: Session, now: datetime) -> list[User]:
    """Las cuentas a las que se les avisa, en orden estable."""
    paid = (
        select(Subscription.id)
        .where(
            Subscription.user_id == User.id,
            Subscription.status.in_(_PAID),
            Subscription.current_period_end > now,
        )
        .exists()
    )
    return list(
        db.scalars(
            select(User)
            .where(User.is_active.is_(True), User.email_verified.is_(True), paid)
            .order_by(User.created_at, User.id)
        )
    )


def pending_for(
    documents: list[LegalDocument],
    accepted: dict[str, int],
    notified: set[uuid.UUID],
) -> list[LegalDocument]:
    """De `documents`, los que a una cuenta le falta que se le avisen: no los
    acepto (ni una version posterior) y no se le aviso de esa version."""
    return [
        doc
        for doc in documents
        if accepted.get(doc.kind, 0) < doc.version and doc.id not in notified
    ]


def send_legal_notices(
    db: Session,
    sender: EmailSender,
    now: datetime,
    *,
    limit: int = NOTICES_PER_RUN,
    daily_limit: int | None = None,
) -> NoticeReport:
    """Envia una tanda de avisos. Hace commit por correo enviado."""
    report = NoticeReport()
    documents = notifiable_documents(db)
    if not documents:
        return report

    cap = notice_daily_limit() if daily_limit is None else daily_limit
    budget = batch_size(limit, cap, _sent_today(db, now))
    if budget == 0:
        report.deferred_by_daily_limit = cap > 0
        return report

    users = _recipients(db, now)
    user_ids = [user.id for user in users]
    accepted: dict[uuid.UUID, dict[str, int]] = defaultdict(dict)
    for user_id, kind, version in db.execute(
        select(UserConsent.user_id, LegalDocument.kind, func.max(LegalDocument.version))
        .join(LegalDocument, LegalDocument.id == UserConsent.legal_document_id)
        .where(UserConsent.user_id.in_(user_ids))
        .group_by(UserConsent.user_id, LegalDocument.kind)
    ):
        accepted[user_id][kind] = version
    notified: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for user_id, document_id in db.execute(
        select(LegalNotice.user_id, LegalNotice.legal_document_id).where(
            LegalNotice.user_id.in_(user_ids),
            LegalNotice.legal_document_id.in_([doc.id for doc in documents]),
        )
    ):
        notified[user_id].add(document_id)

    for user in users:
        if report.sent + report.failed >= budget:
            # Quedan cuentas: siguen en la proxima corrida.
            report.deferred_by_daily_limit = budget < limit
            break
        pending = pending_for(documents, accepted[user.id], notified[user.id])
        if not pending:
            continue
        if not _send(sender, _message(db, user, pending, now), report):
            continue
        for doc in pending:
            db.add(LegalNotice(user_id=user.id, legal_document_id=doc.id, sent_at=now))
        db.commit()
        report.sent += 1
        report.recipients.append(user.email)
    return report


def _message(
    db: Session, user: User, documents: list[LegalDocument], now: datetime
) -> EmailMessage:
    base = get_settings().frontend_base_url.rstrip("/")
    automatic = db.scalar(
        select(func.count())
        .select_from(Subscription)
        .where(
            Subscription.user_id == user.id,
            Subscription.status.in_(("active", "past_due")),
            Subscription.renewal_mode == "automatic",
            Subscription.current_period_end > now,
        )
    )
    return build_email(
        "legal_update",
        to=user.email,
        display_name=user.display_name,
        documents=[
            {
                "title": doc.title,
                "version": doc.version,
                "published_at": doc.published_at,
                "url": f"{base}{PUBLIC_PATHS[doc.kind]}",
            }
            for doc in documents
        ],
        renews_automatically=bool(automatic),
        account_url=f"{base}/cuenta",
    )


def _send(sender: EmailSender, message: EmailMessage, report: NoticeReport) -> bool:
    try:
        sender.send(message)
    except Exception:
        # Sin correo no hay fila: se reintenta en la siguiente corrida.
        logger.exception("Aviso legal: no se pudo enviar a %s", message.to)
        report.failed += 1
        return False
    return True
