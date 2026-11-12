import { AccessGate } from "@/components/AccessGate";
import { GuidesPage } from "@/components/guides/GuidesPage";
import { privateMetadata } from "@/lib/site";

export const metadata = privateMetadata("Guías");

export default async function GuiasPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  // Las guías son un endpoint de juego: sin acceso respondería 403.
  return (
    <AccessGate>
      <GuidesPage slug={slug} />
    </AccessGate>
  );
}
