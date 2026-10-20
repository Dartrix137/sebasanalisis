import { privateMetadata } from "@/lib/site";

export const metadata = privateMetadata("Bitácora");

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
