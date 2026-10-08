import { AccessGate } from "@/components/AccessGate";

import { RouletteSession } from "./RouletteSession";

export default async function RouletteSessionPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  // Sin acceso no hay mesa. Y la primera vez que se entra, la compuerta
  // muestra además la pantalla que explica qué hace y qué no hace la
  // plataforma (§6.3).
  return (
    <AccessGate onboarding>
      <RouletteSession sessionId={sessionId} />
    </AccessGate>
  );
}
