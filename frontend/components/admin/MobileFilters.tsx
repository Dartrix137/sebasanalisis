"use client";

/**
 * Filtros de una lista del admin que en el celular se pliegan detrás de un
 * botón: cinco selectores apilados ocupaban la pantalla entera antes del primer
 * resultado. Desde tableta van siempre a la vista, en la grilla del formulario
 * (`display: contents` no agrega una caja: los campos siguen siendo celdas de
 * esa grilla).
 */

import { useId, useState } from "react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui";

export function MobileFilters({
  active,
  children,
}: {
  /** Cuántos filtros tienen un valor distinto del de "todos". */
  active: number;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        className="sm:hidden"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "Ocultar filtros" : active > 0 ? `Filtros (${active})` : "Filtros"}
      </Button>
      <div id={id} className={`contents ${open ? "" : "max-sm:hidden"}`}>
        {children}
      </div>
    </>
  );
}
