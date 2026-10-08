import { notFound } from "next/navigation";

import { LegalDocumentView } from "@/components/legal/LegalDocumentView";
import { kindFromSlug } from "@/lib/legal";

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
