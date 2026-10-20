import type { Metadata } from "next";
import { Barlow_Condensed, Inter } from "next/font/google";
import "./globals.css";
import { LegalFooter } from "@/components/LegalFooter";
import { SessionProvider } from "@/lib/session";
import { SITE_URL, TITLE_TEMPLATE } from "@/lib/site";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
// Condensada como los números impresos en el paño y el cilindro de la ruleta.
const display = Barlow_Condensed({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-display",
});

// Cada carpeta pone su título con un `layout.tsx` de servidor (las páginas son
// de cliente y no pueden exportar metadatos); la plantilla le suma la marca.
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: "Sebasanálisis", template: TITLE_TEMPLATE },
  description:
    "Registra los números de una mesa de ruleta y, después de cada giro, recibe una recomendación estadística sobre lo ya registrado, o la indicación de no apostar.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className={`${inter.variable} ${display.variable}`}>
      <body className="flex min-h-screen flex-col font-sans">
        <SessionProvider>
          {/* Cada página llena el alto que deja el pie con `flex-1`. */}
          <div className="flex flex-1 flex-col">{children}</div>
        </SessionProvider>
        <LegalFooter />
      </body>
    </html>
  );
}
