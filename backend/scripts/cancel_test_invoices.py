"""Aparta las facturas de los pagos de prueba antes de encender Siigo (Fase 5,
paso 5.6; `core/sandbox_payments.py`).

Los pagos aprobados en el sandbox de Tipster Page tienen su factura `pending`.
Con `INVOICE_ISSUER=siigo` en la empresa real saldrian a la DIAN. Este script
las pasa a `cancelled` con el motivo `test_payment`, con una fila en la
bitacora por cada una. Solo toca facturas que nunca se intentaron enviar, de
pagos aprobados antes de `--antes-de`.

Uso (desde backend/, en el contenedor de la API):

    python scripts/cancel_test_invoices.py --antes-de 2026-11-13T17:00:00Z \\
        --admin admin@ejemplo.com --motivo "Pagos de prueba del sandbox"

Sin `--aplicar` solo lista lo que haria. `--antes-de` es el momento en que la
pasarela paso a produccion (o ahora, si todavia no paso): un pago aprobado
despues es real y su factura tiene que salir. No imprime datos del comprador.
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.core import sandbox_payments  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402


def _moment(value: str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise argparse.ArgumentTypeError("con zona horaria, p. ej. 2026-11-13T17:00:00Z")
    return moment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--antes-de", type=_moment, required=True, dest="before")
    parser.add_argument("--admin", required=True, help="correo del administrador")
    parser.add_argument("--motivo", required=True)
    parser.add_argument("--aplicar", action="store_true")
    args = parser.parse_args()

    now = datetime.now(UTC)
    if args.before > now:
        sys.exit("--antes-de no puede ser futura")
    with SessionLocal() as db:
        admin = db.scalar(
            select(User).where(func.lower(User.email) == args.admin.strip().lower())
        )
        if admin is None or admin.role != "admin":
            sys.exit("--admin tiene que ser el correo de un administrador")
        found = sandbox_payments.candidates(db, args.before)
        print(f"Facturas de pagos de prueba aprobados antes de {args.before.isoformat()}: {len(found)}")
        for item in found:
            print(
                f"  pago {item.payment_id}  {item.amount_cents / 100:.2f} {item.currency}"
                f"  aprobado {item.approved_at.isoformat()}"
            )
        if not args.aplicar:
            print("No se cambio nada. Para apartarlas, repite con --aplicar.")
            return
        try:
            done = sandbox_payments.cancel(db, admin, args.before, args.motivo, now)
        except ValueError as exc:
            db.rollback()
            sys.exit(str(exc))
        db.commit()
        print(f"Apartadas: {len(done)} (cancelled, test_payment), con su fila en la bitacora.")


if __name__ == "__main__":
    main()
