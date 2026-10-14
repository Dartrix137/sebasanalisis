import { AccessGate } from "@/components/AccessGate";
import { MesaScreen } from "@/components/mesa/MesaScreen";

export default async function MesaPage({
  params,
}: {
  params: Promise<{ slug: string; sessionId: string }>;
}) {
  const { slug, sessionId } = await params;
  // Sin acceso no hay mesa. Y la primera vez que se entra, la compuerta
  // muestra además la pantalla que explica qué hace y qué no hace la
  // plataforma (§6.3).
  return (
    <AccessGate onboarding>
      <MesaScreen slug={slug} sessionId={sessionId} />
    </AccessGate>
  );
}
