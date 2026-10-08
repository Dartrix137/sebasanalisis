import { LegalGate } from "@/components/legal/LegalGate";

import { RouletteSession } from "./RouletteSession";

export default async function RouletteSessionPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  // La primera vez que se entra a la mesa, la compuerta muestra además la
  // pantalla que explica qué hace y qué no hace la plataforma (§6.3).
  return (
    <LegalGate onboarding>
      <RouletteSession sessionId={sessionId} />
    </LegalGate>
  );
}
