import { privateMetadata } from "@/lib/site";

export const metadata = privateMetadata("Usuarios");

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
