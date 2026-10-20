import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { LegalDocumentView } from "@/components/legal/LegalDocumentView";
import { LEGAL_DOCUMENTS, kindFromSlug } from "@/lib/legal";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const info = LEGAL_DOCUMENTS.find((d) => d.slug === slug);
  if (!info) return {};
  return { title: info.label, description: `${info.label} de Sebasanálisis.` };
}

/** Página pública de un documento legal: su última versión publicada (§6.2). */
export default async function LegalDocumentPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const kind = kindFromSlug(slug);
  if (!kind) notFound();
  return <LegalDocumentView kind={kind} />;
}
