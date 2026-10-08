"use client";

/**
 * Un documento legal en su página pública: título, versión, fecha y texto. Se
 * lee sin sesión.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { ApiError, legalApi } from "@/lib/api-client";
import { formatLegalDate } from "@/lib/legal";
import type { LegalDocumentResponse, LegalKind } from "@/lib/types/legal";

import { BrandMark, ErrorBox } from "../ui";
import { Markdown } from "./Markdown";

export function LegalDocumentView({ kind }: { kind: LegalKind }) {
  const [document, setDocument] = useState<LegalDocumentResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    legalApi
      .current(kind)
      .then(setDocument)
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "No se pudo cargar el documento"),
      );
  }, [kind]);

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 px-4 pb-12 pt-8 sm:px-6">
      <Link href="/" className="inline-flex items-center gap-3">
        <BrandMark size={38} />
        <span className="text-base font-extrabold leading-tight">
          Sebas<span className="text-gold">análisis</span>
        </span>
      </Link>

      {error ? (
        <div className="mt-8">
          <ErrorBox message={error} />
        </div>
      ) : null}

      {document ? (
        <article className="mt-8">
          <h1 className="font-display text-4xl font-semibold leading-none tracking-tight sm:text-5xl">
            {document.title}
          </h1>
          <p className="mt-3 text-sm text-muted">
            Versión {document.version} · Publicada el {formatLegalDate(document.published_at)}
          </p>
          <div className="mt-6">
            <Markdown>{document.content_md}</Markdown>
          </div>
        </article>
      ) : null}
    </main>
  );
}
