"use client";

/**
 * Barra superior de toda la aplicación: el logo con el nombre a la izquierda y,
 * a la derecha, el menú de la cuenta (o "Entrar" y "Crear cuenta" sin sesión).
 *
 * Una sola fila también en el celular (decidido el 2026-10-20): antes llevaba
 * el subtítulo, el correo como insignia, "Admin" y "Salir", y en el celular
 * ocupaba dos filas que empujaban la recomendación hacia abajo. Los datos de
 * la mesa viven ahora en la franja de la mesa, no aquí.
 *
 * El menú es un botón que despliega una lista de enlaces (patrón de
 * divulgación, no `role="menu"`): los enlaces siguen siendo enlaces para el
 * teclado y el lector de pantalla. Se cierra con Escape, al tocar fuera y al
 * elegir un enlace.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import { useSession } from "@/lib/session";
import type { UserResponse } from "@/lib/types/auth";

import { BrandMark } from "./ui";

export function AppHeader() {
  const { user, loading } = useSession();

  return (
    <header className="border-b border-edge bg-ink-raised">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-2 sm:px-6">
        <Link
          href={user ? "/dashboard" : "/"}
          className="-ml-1 flex min-h-11 items-center gap-2.5 rounded-lg px-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-gold"
        >
          <BrandMark size={34} />
          <span className="text-lg font-extrabold leading-none tracking-tight">
            Sebas<span className="text-gold">análisis</span>
          </span>
        </Link>

        {loading ? null : user ? (
          <AccountMenu user={user} />
        ) : (
          <nav aria-label="Cuenta" className="flex items-center gap-1.5">
            <Link
              href="/login"
              className="inline-flex min-h-11 items-center rounded-lg px-3 text-sm font-bold text-white hover:text-gold"
            >
              Entrar
            </Link>
            <Link
              href="/register"
              className="inline-flex min-h-11 items-center rounded-lg bg-gold px-3.5 text-sm font-bold text-gold-ink hover:bg-gold-soft"
            >
              Crear cuenta
            </Link>
          </nav>
        )}
      </div>
    </header>
  );
}

const ITEM =
  "flex min-h-11 w-full items-center rounded-lg px-3 text-left text-sm font-bold text-white transition-colors hover:bg-ink-sunken focus-visible:bg-ink-sunken focus-visible:outline-none";

function AccountMenu({ user }: { user: UserResponse }) {
  const { signOut } = useSession();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  const nombre = user.display_name?.trim() || user.email;
  const inicial = nombre.charAt(0).toUpperCase();

  useEffect(() => {
    if (!open) return;
    function fuera(e: MouseEvent) {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    }
    function escape(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      setOpen(false);
      trigger.current?.focus();
    }
    document.addEventListener("mousedown", fuera);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", fuera);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <div ref={box} className="relative">
      <button
        ref={trigger}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label="Menú de la cuenta"
        onClick={() => setOpen((v) => !v)}
        className="flex h-11 w-11 items-center justify-center rounded-full border border-gold/50 bg-ink-sunken font-display text-lg font-bold text-gold transition-colors hover:border-gold aria-expanded:border-gold aria-expanded:bg-gold aria-expanded:text-gold-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold"
      >
        <span aria-hidden>{inicial}</span>
      </button>

      <div
        id={panelId}
        hidden={!open}
        className="absolute right-0 top-full z-30 mt-2 w-64 rounded-card border border-edge bg-ink-raised p-1.5 shadow-2xl shadow-black/50"
      >
        <div className="border-b border-edge px-3 pb-2.5 pt-2">
          <p className="truncate text-sm font-bold text-white">{nombre}</p>
          {user.display_name ? (
            <p className="truncate text-xs text-muted">{user.email}</p>
          ) : null}
          {user.role === "admin" ? <p className="mt-0.5 text-xs text-gold">Administrador</p> : null}
        </div>
        {/* Tocar un enlace cierra el menú, también si lleva a la misma página. */}
        <ul className="py-1" onClick={() => setOpen(false)}>
          <li>
            <Link href="/dashboard" className={ITEM}>
              Mis mesas
            </Link>
          </li>
          <li>
            <Link href="/cuenta" className={ITEM}>
              Mi cuenta
            </Link>
          </li>
          <li>
            <Link href="/planes" className={ITEM}>
              Planes
            </Link>
          </li>
          {user.role === "admin" ? (
            <li>
              <Link href="/admin" className={ITEM}>
                Administración
              </Link>
            </li>
          ) : null}
        </ul>
        <div className="border-t border-edge pt-1">
          <button
            type="button"
            className={`${ITEM} text-muted hover:text-white`}
            onClick={() => {
              signOut();
              router.replace("/login");
            }}
          >
            Salir
          </button>
        </div>
      </div>
    </div>
  );
}
