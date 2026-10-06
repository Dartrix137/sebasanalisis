"use client";

/**
 * Destino del enlace de los correos de verificación y de cambio de correo.
 * Confirma el token al cargar y muestra el resultado.
 */

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { AuthShell, SuccessBox, TextLink } from "@/components/AuthShell";
import { ErrorBox } from "@/components/ui";
import { ApiError, authApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";

type Result = { ok: true; message: string } | { ok: false; message: string };

function VerifyEmail() {
  const token = useSearchParams().get("token") ?? "";
  const { user, loading, refreshUser } = useSession();
  const [result, setResult] = useState<Result | null>(null);
  // El token es de un solo uso: el efecto no puede correr dos veces (React lo
  // hace en desarrollo), o la segunda llamada mostraría "enlace vencido" sobre
  // un correo que sí quedó confirmado.
  const started = useRef(false);

  useEffect(() => {
    if (loading || started.current) return;
    started.current = true;
    if (!token) {
      setResult({
        ok: false,
        message: "A este enlace le falta información. Ábrelo completo desde el correo.",
      });
      return;
    }
    authApi
      .verifyEmail({ token })
      .then(async ({ message }) => {
        // Con sesión abierta, que el resto de la app vea ya el correo confirmado.
        await refreshUser().catch(() => undefined);
        setResult({ ok: true, message });
      })
      .catch((err) =>
        setResult({
          ok: false,
          message: err instanceof ApiError ? err.message : "No se pudo confirmar el correo",
        }),
      );
  }, [loading, token, refreshUser]);

  if (!result) return <p className="text-center text-sm text-muted">Confirmando tu correo…</p>;

  return (
    <div className="space-y-4">
      {result.ok ? <SuccessBox message={result.message} /> : <ErrorBox message={result.message} />}
      {result.ok ? null : (
        <p className="text-sm leading-relaxed text-muted">
          Los enlaces vencen y solo sirven una vez. Puedes pedir uno nuevo desde tu cuenta.
        </p>
      )}
      <p className="text-center text-sm">
        {user ? (
          <TextLink href={result.ok ? "/dashboard" : "/cuenta"}>
            {result.ok ? "Ir al menú principal" : "Ir a mi cuenta"}
          </TextLink>
        ) : (
          <TextLink href="/login">Iniciar sesión</TextLink>
        )}
      </p>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <AuthShell title="Confirmar correo">
      {/* useSearchParams exige un límite de Suspense al prerenderizar. */}
      <Suspense fallback={null}>
        <VerifyEmail />
      </Suspense>
    </AuthShell>
  );
}
