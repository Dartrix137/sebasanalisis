"use client";

/**
 * Admin: documentos legales (§6.2 de la Fase 4).
 *
 * Cada documento tiene su versión vigente y, como mucho, un borrador de la
 * siguiente. El borrador se escribe en Markdown y se puede guardar las veces
 * que haga falta; publicarlo lo congela. Una versión publicada no se edita: se
 * publica otra, para que cada aceptación apunte al texto exacto que se leyó.
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { SuccessBox } from "@/components/AuthShell";
import { Markdown } from "@/components/legal/Markdown";
import { Badge, Button, Card, Checkbox, ErrorBox, Field } from "@/components/ui";
import { ApiError, adminApi } from "@/lib/api-client";
import { LEGAL_DOCUMENTS, formatLegalDate, legalPath } from "@/lib/legal";
import type { LegalDocumentInfo } from "@/lib/legal";
import { useSession } from "@/lib/session";
import type { AdminLegalDocumentResponse } from "@/lib/types/legal";

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.message : "No se pudo completar la solicitud";
}

export default function AdminLegalPage() {
  const { user, loading, withToken } = useSession();
  const router = useRouter();
  const [documents, setDocuments] = useState<AdminLegalDocumentResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setDocuments(await withToken((t) => adminApi.listLegalDocuments(t)));
  }, [withToken]);

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    if (user.role !== "admin") {
      router.replace("/dashboard");
      return;
    }
    refresh().catch((e) => setError(messageOf(e)));
  }, [loading, user, router, refresh]);

  if (loading || !user || user.role !== "admin") return null;

  return (
    <main className="mx-auto w-full max-w-4xl flex-1 space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-extrabold">Documentos legales</h1>
          <p className="mt-1 max-w-prose text-sm text-muted">
            Una versión publicada no se edita: para cambiar un texto se publica una versión nueva.
          </p>
        </div>
        <Button variant="ghost" onClick={() => router.push("/admin")}>
          Volver al panel
        </Button>
      </header>

      {error ? <ErrorBox message={error} /> : null}

      {documents
        ? LEGAL_DOCUMENTS.map((info) => (
            <DocumentCard
              key={info.kind}
              info={info}
              versions={documents.filter((d) => d.kind === info.kind)}
              onChanged={refresh}
            />
          ))
        : null}
    </main>
  );
}

function DocumentCard({
  info,
  versions,
  onChanged,
}: {
  info: LegalDocumentInfo;
  /** De la más reciente a la más antigua. */
  versions: AdminLegalDocumentResponse[];
  onChanged: () => Promise<void>;
}) {
  const draft = versions.find((v) => v.published_at === null) ?? null;
  const published = versions.filter((v) => v.published_at !== null);
  const current = published[0] ?? null;
  const [editing, setEditing] = useState(false);

  return (
    <Card>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-bold text-white">{current?.title ?? info.label}</h2>
          <p className="mt-1 text-sm text-muted">
            {current?.published_at
              ? `Vigente: versión ${current.version}, publicada el ${formatLegalDate(current.published_at)}.`
              : "Todavía no hay ninguna versión publicada."}{" "}
            {current ? (
              <a
                href={legalPath(info.kind)}
                target="_blank"
                rel="noopener noreferrer"
                className="font-bold text-gold hover:text-gold-soft"
              >
                Ver página pública
              </a>
            ) : null}
          </p>
        </div>
        {draft ? <Badge>Borrador de la versión {draft.version}</Badge> : null}
      </header>

      {draft || editing ? (
        <DraftEditor
          key={draft?.id ?? "nuevo"}
          info={info}
          draft={draft}
          base={current}
          onCancel={draft ? undefined : () => setEditing(false)}
          onChanged={async () => {
            setEditing(false);
            await onChanged();
          }}
        />
      ) : (
        <Button className="mt-4" variant="ghost" onClick={() => setEditing(true)}>
          Preparar versión nueva
        </Button>
      )}

      {published.length > 1 ? (
        <details className="mt-4 text-sm text-muted">
          <summary className="cursor-pointer font-bold hover:text-white">
            Versiones anteriores ({published.length - 1})
          </summary>
          <ul className="mt-2 space-y-1">
            {published.slice(1).map((v) => (
              <li key={v.id}>
                Versión {v.version}, publicada el{" "}
                {v.published_at ? formatLegalDate(v.published_at) : ""}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </Card>
  );
}

function DraftEditor({
  info,
  draft,
  base,
  onCancel,
  onChanged,
}: {
  info: LegalDocumentInfo;
  /** El borrador guardado, si ya existe. */
  draft: AdminLegalDocumentResponse | null;
  /** La versión vigente: un borrador nuevo parte de su texto. */
  base: AdminLegalDocumentResponse | null;
  onCancel?: () => void;
  onChanged: () => Promise<void>;
}) {
  const { withToken } = useSession();
  const source = draft ?? base;
  const [title, setTitle] = useState(source?.title ?? info.label);
  const [content, setContent] = useState(source?.content_md ?? "");
  const [requiresAcceptance, setRequiresAcceptance] = useState(
    source?.requires_acceptance ?? false,
  );
  const [preview, setPreview] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const id = `legal-${info.kind}`;
  const version = draft?.version ?? (base ? base.version + 1 : 1);

  async function save(): Promise<AdminLegalDocumentResponse> {
    const body = { title, content_md: content, requires_acceptance: requiresAcceptance };
    return withToken((t) =>
      draft
        ? adminApi.updateLegalDocument(t, draft.id, body)
        : adminApi.createLegalDocument(t, { kind: info.kind, ...body }),
    );
  }

  async function run(action: () => Promise<void>) {
    setPending(true);
    setError(null);
    setSaved(false);
    try {
      await action();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      className="mt-4 space-y-4 border-t border-edge pt-4"
      onSubmit={(e) => {
        e.preventDefault();
        run(async () => {
          await save();
          await onChanged();
          setSaved(true);
        });
      }}
    >
      <Field
        label="Título"
        required
        maxLength={200}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />

      <div>
        <div className="mb-1.5 flex items-center justify-between gap-3">
          <label htmlFor={id} className="text-sm font-bold text-white">
            Texto (Markdown)
          </label>
          <button
            type="button"
            className="text-xs font-bold text-gold hover:text-gold-soft"
            onClick={() => setPreview((v) => !v)}
          >
            {preview ? "Seguir editando" : "Vista previa"}
          </button>
        </div>
        {preview ? (
          <div className="rounded-lg border border-edge bg-ink px-4 pb-4 pt-1">
            <Markdown>{content}</Markdown>
          </div>
        ) : (
          <textarea
            id={id}
            required
            rows={16}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            className="w-full rounded-lg border border-edge bg-ink-sunken px-3.5 py-2.5 font-mono text-xs leading-relaxed text-white outline-none focus:border-gold/60"
          />
        )}
        <span className="mt-1 block text-xs text-muted">
          El HTML escrito en el texto no se interpreta.
        </span>
      </div>

      <Checkbox
        checked={requiresAcceptance}
        onChange={(e) => setRequiresAcceptance(e.target.checked)}
      >
        Exigir que todas las cuentas acepten esta versión. Al publicarla, nadie entra a la mesa
        hasta aceptarla.
      </Checkbox>

      {error ? <ErrorBox message={error} /> : null}
      {saved ? <SuccessBox message="Borrador guardado" /> : null}

      {confirming ? (
        <div className="space-y-3 rounded-lg border border-gold/40 bg-gold/10 px-4 py-3">
          <p className="text-sm leading-relaxed text-white">
            Vas a publicar la versión {version}. Pasa a ser la vigente de inmediato y ya no se
            podrá editar.
            {requiresAcceptance
              ? " Todas las cuentas tendrán que aceptarla antes de volver a la mesa."
              : " No se le pedirá a nadie aceptarla de nuevo."}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              disabled={pending}
              onClick={() =>
                run(async () => {
                  // Se guarda lo que hay en pantalla y eso mismo se publica.
                  const guardado = await save();
                  await withToken((t) => adminApi.publishLegalDocument(t, guardado.id));
                  await onChanged();
                })
              }
            >
              {pending ? "Publicando…" : `Sí, publicar la versión ${version}`}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setConfirming(false)}>
              Cancelar
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button type="submit" variant="ghost" disabled={pending}>
            {pending ? "Guardando…" : "Guardar borrador"}
          </Button>
          <Button type="button" disabled={pending} onClick={() => setConfirming(true)}>
            Publicar versión {version}
          </Button>
          {onCancel ? (
            <Button type="button" variant="ghost" onClick={onCancel}>
              Descartar
            </Button>
          ) : null}
        </div>
      )}
    </form>
  );
}
