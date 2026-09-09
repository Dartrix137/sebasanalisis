import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { SessionProvider } from "@/lib/session";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "Sebasanálisis",
  description:
    "Análisis estadístico descriptivo de juegos de casino. La ruleta no tiene memoria: cada giro es independiente.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className={inter.variable}>
      <body className="min-h-screen font-sans">
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
