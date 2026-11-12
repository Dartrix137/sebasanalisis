import type { Metadata } from "next";

import { sectionTitle } from "@/lib/site";

export const metadata: Metadata = {
  title: sectionTitle("Planes"),
  description:
    "Planes de suscripción a Sebasanálisis, con cobro en euros (EUR).",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
