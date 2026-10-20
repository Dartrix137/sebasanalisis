import { privateMetadata } from "@/lib/site";

export const metadata = privateMetadata("Juegos");

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
