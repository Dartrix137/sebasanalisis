"use client";

/** Paginación de las listas del admin: el servidor filtra y corta (§4.1). */

import { Button } from "../ui";

export function Pager({
  total,
  offset,
  count,
  pageSize,
  onChange,
}: {
  total: number;
  offset: number;
  count: number;
  pageSize: number;
  onChange: (offset: number) => void;
}) {
  if (total === 0) return null;
  return (
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-edge pt-4 text-sm text-muted">
      <span>
        {offset + 1}–{offset + count} de {total}
      </span>
      <div className="flex gap-2">
        <Button
          variant="ghost"
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - pageSize))}
        >
          Anterior
        </Button>
        <Button
          variant="ghost"
          disabled={offset + count >= total}
          onClick={() => onChange(offset + pageSize)}
        >
          Siguiente
        </Button>
      </div>
    </div>
  );
}
