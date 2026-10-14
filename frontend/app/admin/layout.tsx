"use client";

/**
 * Navegación del admin (§4.1 de la Fase 4): una columna al lado en pantallas
 * anchas y una fila que se desplaza en el celular.
 *
 * Solo se dibuja para un administrador. Cada página sigue revisando la sesión y
 * redirige a quien no lo es; el servidor, además, responde 403 en todo `/admin`.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";

import { AppHeader } from "@/components/AppHeader";
import { useSession } from "@/lib/session";

const SECTIONS: readonly { href: string; label: string }[] = [
  { href: "/admin", label: "Resumen" },
  { href: "/admin/usuarios", label: "Usuarios" },
  { href: "/admin/suscripciones", label: "Suscripciones" },
  { href: "/admin/pagos", label: "Pagos" },
  { href: "/admin/planes", label: "Planes" },
  { href: "/admin/descuentos", label: "Descuentos" },
  { href: "/admin/juegos", label: "Juegos" },
  { href: "/admin/legal", label: "Documentos legales" },
  { href: "/admin/motor", label: "Motor" },
  { href: "/admin/auditoria", label: "Bitácora" },
];

function isCurrent(pathname: string, href: string): boolean {
  return href === "/admin" ? pathname === "/admin" : pathname.startsWith(href);
}

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useSession();
  const pathname = usePathname();

  if (loading || user?.role !== "admin") return <>{children}</>;

  return (
    <>
      <AppHeader />
      <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col lg:flex-row">
        <nav
          aria-label="Administración"
          className="border-b border-edge lg:w-56 lg:shrink-0 lg:border-b-0 lg:border-r"
        >
          <ul className="flex gap-1 overflow-x-auto px-4 py-2 lg:sticky lg:top-0 lg:flex-col lg:overflow-visible lg:px-3 lg:py-6">
            {SECTIONS.map((s) => {
              const current = isCurrent(pathname, s.href);
              return (
                <li key={s.href} className="shrink-0">
                  <Link
                    href={s.href}
                    aria-current={current ? "page" : undefined}
                    className={`block whitespace-nowrap rounded-lg px-3 py-2 text-sm font-bold transition-colors ${
                      current
                        ? "bg-gold/15 text-gold"
                        : "text-muted hover:bg-ink-raised hover:text-white"
                    }`}
                  >
                    {s.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </>
  );
}
