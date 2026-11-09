"""Lista los catalogos de la cuenta de Siigo para elegir los ids de la factura
(docs/PLATAFORMA_COMPLETA.md §3.17, "Paso 5.4", punto 10).

Uso (desde backend/, con SIIGO_USERNAME, SIIGO_ACCESS_KEY y SIIGO_PARTNER_ID en
el .env):

    python scripts/siigo_catalogs.py            # todo
    python scripts/siigo_catalogs.py productos  # solo uno

Solo lee: no crea nada en Siigo. No imprime el token ni las credenciales. Imprime
los tipos de comprobante de factura electronica (SIIGO_DOCUMENT_TYPE_ID), las
formas de pago (SIIGO_PAYMENT_TYPE_ID), los usuarios activos (SIIGO_SELLER_ID),
los productos de tipo servicio (SIIGO_PRODUCT_CODE) y los grupos de inventario
(que pide Siigo para crear un producto). Respeta la espera entre peticiones
(`SIIGO_MIN_INTERVAL_SECONDS`; en la empresa de pruebas, 8).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.invoicing.siigo import SiigoIssuer, _results  # noqa: E402


def _issuer() -> SiigoIssuer:
    s = get_settings()
    missing = [n for n in ("siigo_username", "siigo_access_key", "siigo_partner_id")
               if not getattr(s, n)]
    if missing:
        sys.exit(f"Faltan en el .env: {', '.join(m.upper() for m in missing)}")
    return SiigoIssuer(
        username=s.siigo_username,
        access_key=s.siigo_access_key,
        partner_id=s.siigo_partner_id,
        document_type_id=0,
        seller_id=0,
        payment_type_id=0,
        product_code="",
        base_url=s.siigo_api_base_url,
        min_interval_seconds=s.siigo_min_interval_seconds,
    )


CATALOGS = {
    "comprobantes": (
        "/v1/document-types", {"type": "FV"},
        lambda r: r.get("electronic_type") == "ElectronicInvoice" and r.get("active"),
        ("id", "code", "name", "electronic_type", "cost_center", "automatic_number"),
    ),
    "pagos": (
        "/v1/payment-types", {"document_type": "FV"},
        lambda r: r.get("active") and not r.get("due_date"),
        ("id", "name", "type"),
    ),
    "usuarios": ("/v1/users", None, lambda r: r.get("active"), ("id", "first_name", "last_name")),
    "productos": (
        "/v1/products", None,
        lambda r: (r.get("type") or "").lower() == "service",
        ("code", "name", "type", "tax_classification", "active"),
    ),
    "grupos": ("/v1/account-groups", None, lambda r: r.get("active"), ("id", "name")),
}


def main(which: list[str]) -> None:
    issuer = _issuer()
    for name in which or list(CATALOGS):
        path, params, keep, fields = CATALOGS[name]
        rows = [r for r in _results(issuer._request("GET", path, params=params)) if keep(r)]
        print(f"\n== {name} ({path}): {len(rows)}")
        for row in rows[:40]:
            print("  " + " | ".join(str(row.get(f)) for f in fields))
        if len(rows) > 40:
            print(f"  ... y {len(rows) - 40} mas")


if __name__ == "__main__":
    unknown = [a for a in sys.argv[1:] if a not in CATALOGS]
    if unknown:
        sys.exit(f"No conozco {unknown}: elige entre {list(CATALOGS)}")
    main(sys.argv[1:])
