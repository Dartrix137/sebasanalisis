"use client";

/**
 * Elegir una contraseña nueva con el enlace del correo. Al cambiarla, el
 * servidor cierra todas las sesiones de la cuenta; aquí se borra también la que
 * este navegador tuviera guardada, que ya no sirve.
 */

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import {
  AuthShell,
  PASSWORD_HINT,
  PASSWORD_MIN_LENGTH,
  SuccessBox,
  TextLink,
} from "@/components/AuthShell";
import { Button, ErrorBox, PasswordField } from "@/components/ui";
import { ApiError, authApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";

function ResetPasswordForm() {
  const token = useSearchParams().get("token") ?? "";
  const { signOut } = useSession();

  const [password, setPassword] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      const { message } = await authApi.resetPassword({ token, new_password: password });
      signOut();
      setDone(message);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo completar la solicitud");
    } finally {
      setPending(false);
    }
  }

  if (!token) {
    return (
      <div className="space-y-4">
        <ErrorBox message="A este enlace le falta información. Ábrelo completo desde el correo, o pide uno nuevo." />
        <p className="text-center text-xs">
          <TextLink href="/olvide-contrasena">Pedir un enlace nuevo</TextLink>
        </p>
      </div>
    );
  }

  if (done) {
    return (
      <div className="space-y-4">
        <SuccessBox message={done} />
        <p className="text-center text-sm">
          <TextLink href="/login">Iniciar sesión</TextLink>
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <PasswordField
        id="new-password"
        label="Contraseña nueva"
        required
        minLength={PASSWORD_MIN_LENGTH}
        autoComplete="new-password"
        hint={PASSWORD_HINT}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      {error ? <ErrorBox message={error} /> : null}
      <Button type="submit" disabled={pending} className="w-full">
        {pending ? "Un momento…" : "Guardar contraseña"}
      </Button>
      <p className="text-center text-xs">
        <TextLink href="/olvide-contrasena">Pedir un enlace nuevo</TextLink>
      </p>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <AuthShell
      title="Contraseña nueva"
      subtitle="Al guardarla se cierran las sesiones abiertas de tu cuenta en todos los dispositivos."
    >
      {/* useSearchParams exige un límite de Suspense al prerenderizar. */}
      <Suspense fallback={null}>
        <ResetPasswordForm />
      </Suspense>
    </AuthShell>
  );
}
