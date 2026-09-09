import { RouletteSession } from "./RouletteSession";

export default async function RouletteSessionPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  return <RouletteSession sessionId={sessionId} />;
}
