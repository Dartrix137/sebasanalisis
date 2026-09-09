"use client";

/**
 * Barra superior compartida, según `docs/design/ruleta.jpeg`: marca a la
 * izquierda, indicadores y salir a la derecha.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";

import { useSession } from "@/lib/session";

import { Badge, BrandMark, Button } from "./ui";

export function AppHeader({ children }: { children?: React.ReactNode }) {
  const { user, signOut } = useSession();
  const router = useRouter();

  return (
    <header className="border-b border-edge bg-ink-raised">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-3 sm:gap-3 sm:px-6">
        <Link href="/dashboard" className="flex items-center gap-3">
          <BrandMark size={38} />
          <span>
            <span className="block text-base font-extrabold leading-tight">
              Sebas<span className="text-gold">análisis</span>
            </span>
            <span className="hidden text-xs text-muted sm:block">
              Análisis estadístico descriptivo de juegos de casino
            </span>
          </span>
        </Link>

        <div className="flex flex-wrap items-center gap-2">
          {children}
          {user ? <Badge>{user.display_name ?? user.email}</Badge> : null}
          {user?.role === "admin" ? (
            <Button variant="ghost" onClick={() => router.push("/admin")}>
              Admin
            </Button>
          ) : null}
          <Button
            variant="ghost"
            onClick={() => {
              signOut();
              router.replace("/login");
            }}
          >
            Salir
          </Button>
        </div>
      </div>
    </header>
  );
}
