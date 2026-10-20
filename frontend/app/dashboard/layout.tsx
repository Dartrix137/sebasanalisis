import { privateMetadata } from "@/lib/site";

export const metadata = privateMetadata("Inicio");

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
