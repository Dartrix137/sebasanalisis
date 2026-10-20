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
      {/*
        En el celular: marca y botones en la primera fila, indicadores y cuenta
        en la segunda. Antes cada grupo ocupaba su propia fila y el encabezado
        empujaba la recomendación hacia abajo. Se reordena con `order`, sin
        repetir nada en el DOM.
      */}
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 sm:px-6">
        <Link href="/dashboard" className="order-1 mr-auto flex items-center gap-3">
          <BrandMark size={38} />
          <span>
            <span className="block text-base font-extrabold leading-tight">
              Sebas<span className="text-gold">análisis</span>
            </span>
            <span className="hidden text-xs text-muted sm:block">
              Recomendación estadística sobre los números que registras
            </span>
          </span>
        </Link>

        <div className="order-3 flex w-full flex-wrap items-center gap-2 sm:order-2 sm:w-auto">
          {children}
          {user ? (
            <Link
              href="/cuenta"
              title="Mi cuenta"
              className="min-w-0 max-w-full rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-gold"
            >
              <Badge>
                <span className="inline-block max-w-[7rem] truncate align-bottom sm:max-w-[15rem]">
                  {user.display_name ?? user.email}
                </span>
              </Badge>
            </Link>
          ) : null}
        </div>

        <div className="order-2 flex items-center gap-2 sm:order-3">
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
