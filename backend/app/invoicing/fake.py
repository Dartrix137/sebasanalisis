"""Emisor simulado (`INVOICE_ISSUER=fake`): solo desarrollo y Playwright.

No sale a la red. Da cada factura por aceptada con un CUFE inventado, y
devuelve la misma si se repite la `Idempotency-Key`, como Siigo.
"""

from __future__ import annotations

import hashlib

from app.invoicing.base import InvoiceDraft, IssuedInvoice


class FakeInvoiceIssuer:
    name = "fake"
    enabled = True

    def __init__(self) -> None:
        self._by_key: dict[str, IssuedInvoice] = {}
        self._by_id: dict[str, IssuedInvoice] = {}

    def describe(self) -> str:
        return "simulada"

    def check_ready(self) -> None:
        return None

    def issue(self, draft: InvoiceDraft) -> IssuedInvoice:
        found = self._by_key.get(draft.idempotency_key)
        if found is not None:
            return found
        number = len(self._by_key) + 1
        issued = IssuedInvoice(
            provider_id=f"fake-{draft.idempotency_key}",
            name=f"FV-SIM-{number}",
            total=draft.amount,
            stamp_status="Accepted",
            cufe=hashlib.sha256(draft.idempotency_key.encode()).hexdigest(),
            mail_status="sent",
        )
        self._by_key[draft.idempotency_key] = issued
        self._by_id[issued.provider_id] = issued
        return issued

    def fetch(self, provider_id: str) -> IssuedInvoice:
        return self._by_id[provider_id]

    def stamp_errors(self, provider_id: str) -> list[str]:
        return []
