import { AccessGate } from "@/components/AccessGate";
import { GamePage } from "@/components/mesa/GamePage";

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
