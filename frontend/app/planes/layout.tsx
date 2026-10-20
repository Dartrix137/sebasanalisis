import type { Metadata } from "next";

import { sectionTitle } from "@/lib/site";

export const metadata: Metadata = {
  title: sectionTitle("Planes"),
  description:
    "Planes de suscripción a Sebasanálisis, con cobro en pesos colombianos (COP). La suscripción da acceso a la plataforma; no cambia el resultado de ningún juego ni la ventaja de la casa.",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
