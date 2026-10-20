import { privateMetadata } from "@/lib/site";

export const metadata = privateMetadata("Contraseña nueva");

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
