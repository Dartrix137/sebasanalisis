"""Job de renovaciones (docs/PLATAFORMA_COMPLETA.md §3.5). Se programa cada hora.

    python scripts/run_renewals.py

Cobra las suscripciones de renovacion automatica cuyo cobro toca, avisa por
correo antes de cada cobro y antes de cada vencimiento, y deja vencidas las que
terminaron. Tambien envia los avisos de los traslados de precio y, por tandas,
los de una version nueva de un documento legal (§6.7). Es idempotente: se puede correr dos veces seguidas, o en paralelo,
sin cobrar dos veces (ver `app/core/renewals.py`).

Sale con codigo 0 si corrio (o si otra corrida tenia el candado) y con 1 si
alguna suscripcion fallo o algun aviso previo al cobro no salio, para que el
programador de tareas lo marque.
"""

import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.core.email import get_email_sender, send_safely  # noqa: E402
from app.core.legal_notices import send_legal_notices  # noqa: E402
from app.core.monitoring import init_monitoring  # noqa: E402
from app.core.price_changes import send_notices as send_price_notices  # noqa: E402
from app.core.renewals import advisory_lock, run_renewals  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.payments.base import get_payment_provider  # noqa: E402

logger = logging.getLogger("app.renewals")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s - %(message)s")
    init_monitoring(get_settings().sentry_dsn)
    provider = get_payment_provider()
    logger.info("Renovaciones: pagos %s", provider.describe())

    with advisory_lock(engine) as acquired:
        if not acquired:
            logger.info("Renovaciones: ya hay otra corrida en curso; esta no hace nada")
            return 0
        sender = get_email_sender()
        with SessionLocal() as db:
            report = run_renewals(db, provider, sender, datetime.now(UTC))
            # Los avisos de un traslado de precio se envian aqui, uno por uno:
            # su plazo de 30 dias corre solo si el correo salio (§4.10).
            notices = send_price_notices(db, sender, datetime.now(UTC))
            # El aviso de una version nueva de los terminos o de la politica de
            # datos, por tandas y con su propio tope diario (§6.7).
            legal = send_legal_notices(db, sender, datetime.now(UTC))

    for message in report.emails:
        send_safely(sender, message)
    logger.info("Renovaciones: %s correos=%d", report.summary(), len(report.emails))
    logger.info(
        "Traslados de precio: avisos=%d fallidos=%d cerrados=%d",
        notices.sent,
        notices.failed,
        notices.closed,
    )
    logger.info(
        "Avisos legales: enviados=%d fallidos=%d%s",
        legal.sent,
        legal.failed,
        " (quedan para manana: tope diario)" if legal.deferred_by_daily_limit else "",
    )
    # Un aviso que no salio tambien marca la corrida: sin aviso no se cobra.
    return 1 if report.errors or report.notices_failed else 0


if __name__ == "__main__":
    sys.exit(main())
