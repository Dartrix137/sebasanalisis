"use client";

/**
 * Navegación del admin (§4.1 de la Fase 4): una columna al lado en pantallas
 * anchas y, en el celular y la tableta, un selector de sección (2026-10-20):
 * la fila que se desplazaba de lado escondía la mitad de las secciones.
 *
 * Solo se dibuja para un administrador. Cada página sigue revisando la sesión y
 * redirige a quien no lo es; el servidor, además, responde 403 en todo `/admin`.
 */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

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

export function AdminShell({ children }: { children: React.ReactNode }) {
  const { user, loading } = useSession();
  const pathname = usePathname();
  const router = useRouter();
  const isAdmin = !loading && user?.role === "admin";

  if (!isAdmin) return <>{children}</>;

  const actual = SECTIONS.find((s) => isCurrent(pathname, s.href))?.href ?? "/admin";

  return (
    <>
      <AppHeader />
      <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col lg:flex-row">
        <div className="border-b border-edge px-4 py-3 lg:hidden">
          <label className="flex items-center gap-3">
            <span className="shrink-0 text-sm font-bold text-muted">Administración</span>
            <select
              value={actual}
              onChange={(e) => router.push(e.target.value)}
              className="min-h-11 w-full rounded-lg border border-edge bg-ink-sunken px-3 text-base font-bold text-white outline-none focus:border-gold/60"
            >
              {SECTIONS.map((s) => (
                <option key={s.href} value={s.href}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <nav
          aria-label="Administración"
          className="hidden border-r border-edge lg:block lg:w-56 lg:shrink-0"
        >
          <ul className="sticky top-0 flex flex-col gap-1 px-3 py-6">
            {SECTIONS.map((s) => {
              const current = isCurrent(pathname, s.href);
              return (
                <li key={s.href}>
                  <Link
                    href={s.href}
                    aria-current={current ? "page" : undefined}
                    className={`flex min-h-11 items-center whitespace-nowrap rounded-lg px-3 text-sm font-bold transition-colors ${
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
