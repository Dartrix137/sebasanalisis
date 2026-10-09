"use client";

/**
 * Admin: bitácora de acciones de administradores (§4.6 de la Fase 4). Solo
 * lectura: no hay cómo editarla ni borrarla.
 */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Pager } from "@/components/admin/Pager";
import { Button, Card, ErrorBox } from "@/components/ui";
import { ApiError, adminApi } from "@/lib/api-client";
import { actionLabel, describeChange, formatDateTime } from "@/lib/admin";
import { useSession } from "@/lib/session";
import type { AuditLogListResponse } from "@/lib/types/admin";

const PAGE_SIZE = 50;

export default function AdminAuditPage() {
  const { user, loading, withToken } = useSession();
  const router = useRouter();
  const [page, setPage] = useState<AuditLogListResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    if (user.role !== "admin") {
      router.replace("/dashboard");
      return;
    }
    withToken((t) => adminApi.auditLog(t, { limit: PAGE_SIZE, offset }))
      .then(setPage)
      .catch((e) => setError(e instanceof ApiError ? e.message : "No se pudo cargar la bitácora"));
  }, [loading, user, router, withToken, offset]);

  if (loading || !user || user.role !== "admin") return null;

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-extrabold">Bitácora</h1>
          <p className="mt-1 max-w-prose text-sm text-muted">
            Lo que los administradores han hecho sobre accesos, cuentas, planes, cupones y
            documentos legales. No se puede editar ni borrar.
          </p>
        </div>
        <Button variant="ghost" onClick={() => router.push("/admin")}>
          Volver al panel
        </Button>
      </header>

      {error ? <ErrorBox message={error} /> : null}

      {page ? (
        <Card>
          {page.items.length === 0 ? (
            <p className="text-sm text-muted">Todavía no hay acciones registradas.</p>
          ) : (
            <ul className="divide-y divide-edge">
              {page.items.map((entry) => (
                <li key={entry.id} className="space-y-1 py-3 text-sm">
                  <p className="flex flex-wrap items-baseline justify-between gap-x-4">
                    <span className="font-bold text-white">{actionLabel(entry)}</span>
                    <span className="text-xs text-muted">{formatDateTime(entry.created_at)}</span>
                  </p>
                  <p className="break-words text-xs text-muted">
                    {entry.admin_email} · {entry.target_type} {entry.target_id}
                  </p>
                  <p className="break-words text-xs text-muted">
                    Antes: {describeChange(entry.before)}
                    <br />
                    Después: {describeChange(entry.after)}
                  </p>
                  {entry.reason ? <p className="text-white">Motivo: {entry.reason}</p> : null}
                </li>
              ))}
            </ul>
          )}

          <Pager
            total={page.total}
            offset={page.offset}
            count={page.items.length}
            pageSize={PAGE_SIZE}
            onChange={setOffset}
          />
        </Card>
      ) : null}
    </main>
  );
}
