import type { Metadata } from "next";

import { AccessGate } from "@/components/AccessGate";
import { GamePage } from "@/components/mesa/GamePage";
import { privateMetadata } from "@/lib/site";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  // Del slug y no de la API: el título no espera a ninguna consulta.
  const { slug } = await params;
  const name = slug.replace(/-/g, " ");
  return privateMetadata(name.charAt(0).toUpperCase() + name.slice(1));
}

export default async function JuegoPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  // El menú y abrir una mesa son endpoints de juego: sin acceso responderían
  // 403, así que primero pasa por la compuerta.
  return (
    <AccessGate>
      <GamePage slug={slug} />
    </AccessGate>
  );
}
