import { privateMetadata } from "@/lib/site";

export const metadata = privateMetadata("Mi cuenta");

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
