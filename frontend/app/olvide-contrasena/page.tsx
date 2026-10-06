"use client";

/**
 * Pedir el enlace para restablecer la contraseña. La respuesta es la misma
 * exista o no una cuenta con ese correo: la pantalla tampoco lo revela.
 */

import { useState } from "react";

import { AuthShell, SuccessBox, TextLink } from "@/components/AuthShell";
import { Button, ErrorBox, Field } from "@/components/ui";
import { ApiError, authApi } from "@/lib/api-client";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      const { message } = await authApi.forgotPassword({ email });
      setSent(message);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo completar la solicitud");
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthShell
      title="Restablecer contraseña"
      subtitle="Escribe el correo de tu cuenta y te enviamos un enlace para elegir una contraseña nueva."
    >
      {sent ? (
        <div className="space-y-4">
          <SuccessBox message={sent} />
          <p className="text-sm leading-relaxed text-muted">
            El enlace vence en una hora. Si no llega en unos minutos, revisa la carpeta de correo
            no deseado.
          </p>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <Field
            label="Correo electrónico"
            type="email"
            required
            autoComplete="email"
            placeholder="tucorreo@ejemplo.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          {error ? <ErrorBox message={error} /> : null}
          <Button type="submit" disabled={pending} className="w-full">
            {pending ? "Un momento…" : "Enviar enlace"}
          </Button>
        </form>
      )}

      <p className="mt-5 text-center text-xs">
        <TextLink href="/login">Volver a iniciar sesión</TextLink>
      </p>
    </AuthShell>
  );
}
