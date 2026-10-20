import { privateMetadata, sectionTitle } from "@/lib/site";

export const metadata = { ...privateMetadata("Juegos"), title: sectionTitle("Juegos") };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
