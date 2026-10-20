import { privateMetadata } from "@/lib/site";

export const metadata = privateMetadata("Documentos legales");

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
