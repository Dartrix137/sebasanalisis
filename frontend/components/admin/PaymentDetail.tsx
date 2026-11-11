"use client";

/**
 * Un pago visto por el administrador (§4.3 de la Fase 4): sus datos, la cadena de
 * eventos de la pasarela (incluidos los que llegaron con la firma inválida), los
 * reembolsos registrados, y dos acciones:
 *
 * - Reconsultar en la pasarela: la misma función del webhook. Un pago resuelto
 *   no se vuelve a resolver; lo único que cambia uno aprobado es que la pasarela
 *   lo reporte anulado.
 * - Registrar un reembolso hecho en el panel de la pasarela. Es un registro: no
 *   cambia el pago ni el acceso.
 *
 * La pasarela de cada pago se muestra con `providerLabel` (`lib/admin.ts`). Un
 * pago aprobado muestra además su factura electrónica (§3.17, "Paso 5.4",
 * punto 13): estado, número, CUFE, monto en pesos con sus tasas, a quién va y
 * el último error, con dos acciones más, con motivo y bitácora: reintentar la
 * emisión y reconsultar en Siigo.
 *
 * Y sus notas crédito (§3.17, "Paso 5.4", punto 12): un reembolso registrado o
 * una anulación de la pasarela crea una, que sale cuando la DIAN aceptó la
 * factura; si la factura no se había emitido y se devolvió todo, ya no se
 * emite. Cada nota se puede reintentar o reconsultar, y una factura rechazada
 * de un pago devuelto entero se marca anulada en Siigo Nube.
 */

import { useCallback, useEffect, useState } from "react";

import { SuccessBox } from "@/components/AuthShell";
import { Badge, Button, CardHeader, ErrorBox, Field } from "@/components/ui";
import { ApiError, adminApi } from "@/lib/api-client";
import {
  CREDIT_NOTE_REASON_LABEL,
  CREDIT_NOTE_STATUS_LABEL,
  CREDIT_NOTE_STATUS_TONE,
  CREDIT_NOTE_WAITING_LABEL,
  ID_TYPE_LABEL,
  INVOICE_CANCEL_LABEL,
  INVOICE_STATUS_LABEL,
  INVOICE_STATUS_TONE,
  INVOICE_WAITING_LABEL,
  actionLabel,
  describeChange,
  formatCalendarDate,
  formatDateTime,
  providerLabel,
} from "@/lib/admin";
import { PAYMENT_KIND_LABEL, PAYMENT_STATUS_LABEL } from "@/lib/billing";
import { formatLegalDate } from "@/lib/legal";
import { formatMoney, parseMoneyToCents } from "@/lib/money";
import { useSession } from "@/lib/session";
import type {
  AdminPaymentDetailResponse,
  CreditNoteResponse,
  InvoiceResponse,
  PaymentEventResponse,
} from "@/lib/types/admin";

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.message : "No se pudo completar la solicitud";
}

export function PaymentDetail({
  paymentId,
  onChanged,
}: {
  paymentId: string;
  onChanged: () => void;
}) {
  const { withToken } = useSession();
  const [detail, setDetail] = useState<AdminPaymentDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setDetail(await withToken((t) => adminApi.getPayment(t, paymentId)));
  }, [withToken, paymentId]);

  useEffect(() => {
    load().catch((e) => setError(messageOf(e)));
  }, [load]);

  if (error) {
    return (
      <div className="border-t border-edge p-3.5">
        <ErrorBox message={error} />
      </div>
    );
  }
  if (!detail) return null;
  const p = detail.payment;

  function applied(next: AdminPaymentDetailResponse) {
    setDetail(next);
    onChanged();
  }

  return (
    <div className="space-y-5 border-t border-edge p-3.5" data-testid="detalle-pago">
      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <Data label="Cuenta" value={p.user_email ?? "Cuenta eliminada"} />
        <Data label="Tipo" value={`${PAYMENT_KIND_LABEL[p.kind]} · ${p.plan_name}`} />
        <Data
          label="Monto"
          value={
            formatMoney(p.amount_cents, p.currency) +
            (p.discount_cents > 0
              ? ` (con descuento de ${formatMoney(p.discount_cents, p.currency)})`
              : "")
          }
        />
        <Data label="Estado" value={PAYMENT_STATUS_LABEL[p.status]} />
        <Data label="Pasarela" value={providerLabel(p.provider)} />
        <Data label="Referencia" value={p.reference} />
        <Data label="Transacción en la pasarela" value={p.provider_transaction_id ?? "Sin transacción"} />
        <Data label="Abierto" value={formatDateTime(p.created_at)} />
        <Data label="Resuelto" value={p.resolved_at ? formatDateTime(p.resolved_at) : "—"} />
        {p.period_start && p.period_end ? (
          <Data
            label="Período que pagó"
            value={`Del ${formatLegalDate(p.period_start)} al ${formatLegalDate(p.period_end)}`}
          />
        ) : null}
        {p.failure_reason ? <Data label="Lo que dijo la pasarela" value={p.failure_reason} /> : null}
        {p.refunded_cents > 0 ? (
          <Data label="Reembolsado" value={formatMoney(p.refunded_cents, p.currency)} />
        ) : null}
        {detail.invoice ? null : <Data label="Factura electrónica" value="Sin factura" />}
      </dl>

      {detail.invoice ? (
        <InvoiceSection
          invoice={detail.invoice}
          enabled={detail.invoice_issuer_enabled}
          paymentId={paymentId}
          fullyReversed={p.status === "voided" || p.refunded_cents >= p.amount_cents}
          onDone={applied}
        />
      ) : null}

      {detail.credit_notes.length > 0 ? (
        <CreditNotesSection
          notes={detail.credit_notes}
          enabled={detail.invoice_issuer_enabled}
          paymentId={paymentId}
          onDone={applied}
        />
      ) : null}

      {p.reversed_at ? (
        <p
          role="note"
          className="rounded-lg border border-gold/40 bg-gold/10 px-3.5 py-3 text-sm leading-relaxed text-white"
        >
          <span className="font-bold">
            La pasarela lo anuló después de aprobado ({formatDateTime(p.reversed_at)}).
          </span>{" "}
          {p.reversal_note}
        </p>
      ) : null}

      <section>
        <h3 className="text-sm font-bold text-white">Eventos de la pasarela</h3>
        {detail.events.length === 0 ? (
          <p className="mt-1 text-sm text-muted">No ha llegado ningún evento de este pago.</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {detail.events.map((e) => (
              <EventRow key={e.id} event={e} />
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3 className="text-sm font-bold text-white">Reembolsos registrados</h3>
        {detail.refunds.length === 0 ? (
          <p className="mt-1 text-sm text-muted">Ninguno.</p>
        ) : (
          <ul className="mt-2 space-y-1 text-sm">
            {detail.refunds.map((r) => (
              <li key={r.id} className="text-white">
                <span className="font-bold">{formatMoney(r.amount_cents, r.currency)}</span> el{" "}
                {formatLegalDate(r.refunded_at)}
                {r.provider_refund_id ? ` · en la pasarela: ${r.provider_refund_id}` : ""}
                <span className="block text-xs text-muted">
                  {r.admin_email} · {r.reason}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {p.provider_transaction_id ? (
        <RequeryForm paymentId={p.id} onDone={applied} />
      ) : (
        <p className="rounded-lg border border-edge p-3.5 text-sm text-muted">
          <span className="font-bold text-white">Sin transacción en la pasarela.</span> Este pago no
          llegó a la pasarela o todavía no se sabe su transacción, así que no hay qué reconsultar. Si
          el cliente pagó, el evento de la pasarela lo resolverá.
        </p>
      )}
      {p.status === "approved" && p.refunded_cents < p.amount_cents ? (
        <RefundForm
          paymentId={p.id}
          remainingCents={p.amount_cents - p.refunded_cents}
          currency={p.currency}
          onDone={applied}
        />
      ) : null}

      <section>
        <h3 className="text-sm font-bold text-white">Historial de acciones sobre este pago</h3>
        {detail.audit.length === 0 ? (
          <p className="mt-1 text-sm text-muted">Sin acciones registradas.</p>
        ) : (
          <ul className="mt-2 space-y-2 text-xs text-muted">
            {detail.audit.map((entry) => (
              <li key={entry.id}>
                <span className="font-bold text-white">{actionLabel(entry)}</span> ·{" "}
                {formatDateTime(entry.created_at)} · {entry.admin_email}
                <br />
                {describeChange(entry.before)} → {describeChange(entry.after)}
                {entry.reason ? (
                  <>
                    <br />
                    Motivo: {entry.reason}
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function EventRow({ event }: { event: PaymentEventResponse }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded-lg border border-edge px-3 py-2 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-white">
          {formatDateTime(event.created_at)} · {event.event_type ?? "evento"} · {event.status}
        </span>
        <span className="flex flex-wrap gap-1.5">
          <Badge tone={event.signature_verified ? "ok" : "off"}>
            {event.signature_verified ? "Firma válida" : "Firma inválida"}
          </Badge>
          {event.linked ? null : <Badge>No asociado al pago</Badge>}
          {event.processed_at ? null : <Badge>Sin procesar</Badge>}
        </span>
      </div>
      {event.raw_payload ? (
        <button
          type="button"
          className="mt-1 text-gold underline-offset-2 hover:underline"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {open ? "Ocultar el cuerpo" : "Ver el cuerpo"}
        </button>
      ) : null}
      {open ? (
        <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-all rounded bg-ink-sunken p-2 text-muted">
          {JSON.stringify(event.raw_payload, null, 2)}
        </pre>
      ) : null}
    </li>
  );
}

function InvoiceSection({
  invoice,
  enabled,
  paymentId,
  fullyReversed,
  onDone,
}: {
  invoice: InvoiceResponse;
  enabled: boolean;
  paymentId: string;
  fullyReversed: boolean;
  onDone: (detail: AdminPaymentDetailResponse) => void;
}) {
  const retryable = ["pending", "sending", "failed"].includes(invoice.status);
  const refreshable = ["issued", "rejected"].includes(invoice.status);
  // En Siigo sin aceptar, de un pago devuelto entero: no lleva nota crédito
  // (la contadora), se anula en Siigo Nube.
  const cancellable =
    fullyReversed &&
    invoice.provider_name !== null &&
    (invoice.status === "rejected" || invoice.status === "failed");
  return (
    <section className="space-y-3" data-testid="factura-electronica">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-bold text-white">Factura electrónica</h3>
        <Badge tone={INVOICE_STATUS_TONE[invoice.status]}>
          {INVOICE_STATUS_LABEL[invoice.status]}
        </Badge>
        {enabled ? null : <Badge>Emisión apagada</Badge>}
      </div>
      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <Data label="Día de la operación" value={formatCalendarDate(invoice.operation_date)} />
        {invoice.provider_name ? <Data label="Número" value={invoice.provider_name} /> : null}
        {invoice.issue_date ? (
          <Data label="Fecha de emisión" value={formatCalendarDate(invoice.issue_date)} />
        ) : null}
        {invoice.cop_cents !== null ? (
          <Data label="Valor en pesos" value={formatMoney(invoice.cop_cents, "COP")} />
        ) : null}
        {invoice.usd_cop ? (
          <Data
            label="TRM"
            value={`${invoice.usd_cop} COP/USD del ${
              invoice.usd_cop_date ? formatCalendarDate(invoice.usd_cop_date) : "—"
            }`}
          />
        ) : null}
        {invoice.eur_usd ? (
          <Data
            label="Tasa EUR/USD (BCE)"
            value={`${invoice.eur_usd} del ${
              invoice.eur_usd_date ? formatCalendarDate(invoice.eur_usd_date) : "—"
            }`}
          />
        ) : null}
        {invoice.buyer_name ? (
          <Data
            label="A nombre de"
            value={`${invoice.buyer_name} · ${
              ID_TYPE_LABEL[invoice.buyer_id_type ?? ""] ?? invoice.buyer_id_type
            } ${invoice.buyer_id_number ?? ""}`}
          />
        ) : null}
        {invoice.cufe ? <Data label="CUFE" value={invoice.cufe} /> : null}
        {invoice.stamp_status ? <Data label="Estado en Siigo" value={invoice.stamp_status} /> : null}
        {invoice.mail_status ? <Data label="Correo de Siigo" value={invoice.mail_status} /> : null}
        {invoice.attempts > 0 ? <Data label="Intentos" value={String(invoice.attempts)} /> : null}
        {invoice.next_attempt_at && invoice.status !== "failed" ? (
          <Data label="Próximo intento" value={formatDateTime(invoice.next_attempt_at)} />
        ) : null}
      </dl>
      {invoice.waiting_reason ? (
        <p className="text-sm text-muted">
          {INVOICE_WAITING_LABEL[invoice.waiting_reason] ?? invoice.waiting_reason}
        </p>
      ) : null}
      {invoice.status === "cancelled" ? (
        <p className="text-sm text-muted">
          {INVOICE_CANCEL_LABEL[invoice.cancel_reason ?? ""] ?? invoice.cancel_reason}
          {invoice.cancelled_at ? ` · ${formatDateTime(invoice.cancelled_at)}` : ""}
        </p>
      ) : null}
      {invoice.last_error_message ? (
        <ErrorBox
          message={`Último error de Siigo${
            invoice.last_error_codes?.length ? ` (${invoice.last_error_codes.join(", ")})` : ""
          }: ${invoice.last_error_message}`}
        />
      ) : null}
      {invoice.dian_errors?.length ? (
        <ErrorBox message="La DIAN la rechazó:" details={invoice.dian_errors} />
      ) : null}
      {enabled && retryable ? (
        <InvoiceActionForm
          paymentId={paymentId}
          action="retry"
          title="Reintentar la emisión"
          subtitle={
            invoice.status === "failed" && invoice.provider_name
              ? `La vuelve a crear ahora, con los datos de facturación actuales de la cuenta. Antes anula en Siigo Nube la ${invoice.provider_name}, que quedó mal: si no, el pago quedaría con dos facturas.`
              : "La intenta otra vez ahora. Si falló, toma los datos de facturación actuales de la cuenta."
          }
          onDone={onDone}
        />
      ) : null}
      {enabled && refreshable ? (
        <InvoiceActionForm
          paymentId={paymentId}
          action="refresh"
          title="Reconsultar en Siigo"
          subtitle="Pregunta a Siigo por su estado ante la DIAN: por ejemplo, después de corregirla y reenviarla desde Siigo Nube."
          onDone={onDone}
        />
      ) : null}
      {cancellable ? (
        <InvoiceActionForm
          paymentId={paymentId}
          action="cancel"
          title="Marcar anulada en Siigo Nube"
          subtitle={`El pago se devolvió entero y la DIAN no aceptó la ${invoice.provider_name}: no lleva nota crédito. Anúlala primero en Siigo Nube; aquí solo queda constancia, y sus notas crédito pendientes se cancelan.`}
          onDone={onDone}
        />
      ) : null}
    </section>
  );
}

function CreditNotesSection({
  notes,
  enabled,
  paymentId,
  onDone,
}: {
  notes: CreditNoteResponse[];
  enabled: boolean;
  paymentId: string;
  onDone: (detail: AdminPaymentDetailResponse) => void;
}) {
  return (
    <section className="space-y-3" data-testid="notas-credito">
      <h3 className="text-sm font-bold text-white">Notas crédito</h3>
      <ul className="space-y-3">
        {notes.map((note) => (
          <CreditNoteItem
            key={note.id}
            note={note}
            enabled={enabled}
            paymentId={paymentId}
            onDone={onDone}
          />
        ))}
      </ul>
    </section>
  );
}

function CreditNoteItem({
  note,
  enabled,
  paymentId,
  onDone,
}: {
  note: CreditNoteResponse;
  enabled: boolean;
  paymentId: string;
  onDone: (detail: AdminPaymentDetailResponse) => void;
}) {
  const retryable =
    note.status === "pending" ||
    note.status === "sending" ||
    (note.status === "failed" && note.provider_name === null);
  const refreshable = note.status === "issued" || note.status === "rejected";
  return (
    <li className="space-y-3 rounded-lg border border-edge p-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={CREDIT_NOTE_STATUS_TONE[note.status]}>
          {CREDIT_NOTE_STATUS_LABEL[note.status]}
        </Badge>
        <span className="text-sm text-muted">
          {CREDIT_NOTE_REASON_LABEL[note.reason] ?? `Motivo ${note.reason}`}
          {note.refund_id ? " · por un reembolso" : " · por una anulación de la pasarela"}
        </span>
      </div>
      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <Data label="Devuelto" value={formatMoney(note.amount_cents, note.currency)} />
        {note.cop_cents !== null ? (
          <Data label="Valor en pesos" value={formatMoney(note.cop_cents, "COP")} />
        ) : null}
        {note.provider_name ? <Data label="Número" value={note.provider_name} /> : null}
        {note.issue_date ? (
          <Data label="Fecha de emisión" value={formatCalendarDate(note.issue_date)} />
        ) : null}
        {note.cude ? <Data label="CUDE" value={note.cude} /> : null}
        {note.stamp_status ? <Data label="Estado en Siigo" value={note.stamp_status} /> : null}
        {note.mail_status ? <Data label="Correo de Siigo" value={note.mail_status} /> : null}
        {note.attempts > 0 ? <Data label="Intentos" value={String(note.attempts)} /> : null}
        {note.next_attempt_at && note.status !== "failed" ? (
          <Data label="Próximo intento" value={formatDateTime(note.next_attempt_at)} />
        ) : null}
      </dl>
      {note.waiting_reason ? (
        <p className="text-sm text-muted">
          {CREDIT_NOTE_WAITING_LABEL[note.waiting_reason] ?? note.waiting_reason}
        </p>
      ) : null}
      {note.last_error_message ? (
        <ErrorBox
          message={`Último error de Siigo${
            note.last_error_codes?.length ? ` (${note.last_error_codes.join(", ")})` : ""
          }: ${note.last_error_message}`}
        />
      ) : null}
      {enabled && retryable ? (
        <InvoiceActionForm
          paymentId={paymentId}
          creditNoteId={note.id}
          action="retry"
          title="Reintentar la nota crédito"
          subtitle="La intenta otra vez ahora, si su factura ya está aceptada por la DIAN."
          onDone={onDone}
        />
      ) : null}
      {enabled && refreshable ? (
        <InvoiceActionForm
          paymentId={paymentId}
          creditNoteId={note.id}
          action="refresh"
          title="Reconsultar la nota en Siigo"
          subtitle="Pregunta a Siigo por su estado ante la DIAN."
          onDone={onDone}
        />
      ) : null}
    </li>
  );
}

function InvoiceActionForm({
  paymentId,
  creditNoteId,
  action,
  title,
  subtitle,
  onDone,
}: {
  paymentId: string;
  /** Si va, la acción es sobre esa nota crédito, no sobre la factura. */
  creditNoteId?: string;
  action: "retry" | "refresh" | "cancel";
  title: string;
  subtitle: string;
  onDone: (detail: AdminPaymentDetailResponse) => void;
}) {
  const { withToken } = useSession();
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    setSaved(false);
    try {
      const next = await withToken((t) => {
        if (creditNoteId) {
          return action === "retry"
            ? adminApi.retryCreditNote(t, paymentId, creditNoteId, { reason })
            : adminApi.refreshCreditNote(t, paymentId, creditNoteId, { reason });
        }
        if (action === "cancel") return adminApi.cancelInvoice(t, paymentId, { reason });
        return action === "retry"
          ? adminApi.retryInvoice(t, paymentId, { reason })
          : adminApi.refreshInvoice(t, paymentId, { reason });
      });
      setReason("");
      setSaved(true);
      onDone(next);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3 rounded-lg border border-edge p-3.5">
      <CardHeader title={title} subtitle={subtitle} />
      <Field
        label={`Motivo (${title.toLowerCase()})`}
        name={`motivo-${action}${creditNoteId ? `-${creditNoteId}` : ""}`}
        required
        minLength={3}
        maxLength={500}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      {error ? <ErrorBox message={error} /> : null}
      {saved ? <SuccessBox message="Hecho. Quedó en la bitácora." /> : null}
      <Button type="submit" variant="ghost" disabled={pending}>
        {pending ? "Un momento…" : title}
      </Button>
    </form>
  );
}

function RequeryForm({
  paymentId,
  onDone,
}: {
  paymentId: string;
  onDone: (detail: AdminPaymentDetailResponse) => void;
}) {
  const { withToken } = useSession();
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    setSaved(false);
    try {
      const next = await withToken((t) => adminApi.requeryPayment(t, paymentId, { reason }));
      setReason("");
      setSaved(true);
      onDone(next);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3 rounded-lg border border-edge p-3.5">
      <CardHeader
        title="Reconsultar en la pasarela"
        subtitle="Le pregunta a la pasarela por la transacción y aplica lo que responda, igual que el webhook. Un pago ya resuelto no da otro período; si la pasarela lo reporta anulado, se retira el período que pagó."
      />
      <Field
        label="Motivo de la reconsulta"
        required
        minLength={3}
        maxLength={500}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      {error ? <ErrorBox message={error} /> : null}
      {saved ? <SuccessBox message="Reconsultado. El resultado quedó en la bitácora." /> : null}
      <Button type="submit" variant="ghost" disabled={pending}>
        {pending ? "Consultando…" : "Reconsultar en la pasarela"}
      </Button>
    </form>
  );
}

function RefundForm({
  paymentId,
  remainingCents,
  currency,
  onDone,
}: {
  paymentId: string;
  remainingCents: number;
  currency: string;
  onDone: (detail: AdminPaymentDetailResponse) => void;
}) {
  const { withToken } = useSession();
  const [amount, setAmount] = useState("");
  // Fecha local (AAAA-MM-DD) en que se hizo en la pasarela.
  const [date, setDate] = useState("");
  const [providerId, setProviderId] = useState("");
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const cents = parseMoneyToCents(amount);
    if (cents === null || cents <= 0) {
      setError("Escribe el monto, por ejemplo 32 o 12,50");
      return;
    }
    // Mediodía de ese día, hora del equipo del admin, para no caer en el día
    // anterior por la zona horaria; si es hoy y todavía no es mediodía, ahora:
    // el servidor rechaza una fecha futura.
    const refundedAt = new Date(Math.min(new Date(`${date}T12:00:00`).getTime(), Date.now()));
    setPending(true);
    setError(null);
    try {
      const next = await withToken((t) =>
        adminApi.recordRefund(t, paymentId, {
          amount_cents: cents,
          refunded_at: refundedAt.toISOString(),
          provider_refund_id: providerId.trim() || null,
          reason,
        }),
      );
      setAmount("");
      setDate("");
      setProviderId("");
      setReason("");
      onDone(next);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3 rounded-lg border border-edge p-3.5">
      <CardHeader
        title="Registrar un reembolso"
        subtitle={`El reembolso se hace en el panel de la pasarela; aquí solo se registra. No cambia el pago ni el acceso: para quitar el acceso, cancela la suscripción de inmediato. Queda por reembolsar como máximo ${formatMoney(remainingCents, currency)}.`}
      />
      <div className="grid gap-3 sm:grid-cols-3">
        <Field
          label={`Monto (${currency})`}
          required
          inputMode="decimal"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
        <Field
          label="Fecha en la pasarela"
          type="date"
          required
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
        <Field
          label="Id en la pasarela (opcional)"
          maxLength={255}
          value={providerId}
          onChange={(e) => setProviderId(e.target.value)}
        />
      </div>
      <Field
        label="Motivo del reembolso"
        required
        minLength={3}
        maxLength={500}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      {error ? <ErrorBox message={error} /> : null}
      <Button type="submit" variant="ghost" disabled={pending}>
        {pending ? "Guardando…" : "Registrar reembolso"}
      </Button>
    </form>
  );
}

function Data({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="break-words text-white">{value}</dd>
    </div>
  );
}
