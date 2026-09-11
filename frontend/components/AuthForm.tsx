"use client";

/**
 * Pantalla de login/registro, según los mockups `docs/design/login.jpeg` y
 * `register.jpeg`: marca centrada, tarjeta con pestañas, acción primaria dorada.
 *
 * El copy se aparta del mockup a propósito. El original decía "Motor de patrones
 * v3", que sugiere que el sistema anticipa resultados. Ver §0 del documento de
 * arquitectura y la skill `terminologia-no-predictiva`.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, authApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";

import { BrandMark, Button, Card, ErrorBox, Field, PasswordField } from "./ui";

const SUBTITLE = "Registra los números de tu mesa y revisa lo que ya salió. Tu progreso queda guardado en tu cuenta.";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const isRegister = mode === "register";
  const router = useRouter();
  const { signIn, user, loading } = useSession();

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  // Con sesion abierta no hay nada que hacer aqui: mostrar el formulario
  // invita a entrar con otra cuenta sin querer, y deja el boton "atras" del
  // navegador devolviendo a una pantalla de login ya superada.
  useEffect(() => {
    if (!loading && user) router.replace("/dashboard");
  }, [loading, user, router]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      const tokens = isRegister
        ? await authApi.register({
            email,
            password,
            display_name: displayName.trim() || null,
          })
        : await authApi.login({ email, password });
      signIn(tokens);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo completar la solicitud");
    } finally {
      setPending(false);
    }
  }

  // Mientras se lee la sesion guardada no se pinta nada: evita el parpadeo del
  // formulario antes de redirigir a quien ya entro.
  if (loading || user) return null;

  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-4 py-12">
      <BrandMark />
      <h1 className="mt-5 font-display text-5xl font-semibold leading-none tracking-tight">
        Sebas<span className="text-gold">análisis</span>
      </h1>
      <p className="mt-3 max-w-sm text-center text-sm leading-relaxed text-muted">{SUBTITLE}</p>

      <Card className="mt-7 w-full max-w-md">
        <div className="mb-6 grid grid-cols-2 gap-2 rounded-lg bg-ink-sunken p-1">
          <Tab href="/login" active={!isRegister}>
            Iniciar sesión
          </Tab>
          <Tab href="/register" active={isRegister}>
            Crear cuenta
          </Tab>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {isRegister ? (
            <Field
              label="Tu nombre"
              placeholder="Ej: Carlos"
              autoComplete="name"
              maxLength={100}
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          ) : null}

          <Field
            label="Correo electrónico"
            type="email"
            required
            autoComplete="email"
            placeholder="tucorreo@ejemplo.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />

          <PasswordField
            id="password"
            label="Contraseña"
            required
            minLength={8}
            autoComplete={isRegister ? "new-password" : "current-password"}
            hint={isRegister ? "Mínimo 8 caracteres." : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />

          {error ? <ErrorBox message={error} /> : null}

          <Button type="submit" disabled={pending} className="w-full">
            {pending ? "Un momento…" : isRegister ? "Crear mi cuenta" : "Entrar"}
          </Button>
        </form>

        <p className="mt-4 text-center text-xs leading-relaxed text-muted">
          Cada cuenta guarda sus propias sesiones de mesa y su historial estadístico.
        </p>
      </Card>

      <p className="mt-6 max-w-md text-center text-xs leading-relaxed text-muted">
        La ruleta no tiene memoria. Cada giro es independiente. Este análisis es descriptivo,
        no predictivo.
      </p>
    </main>
  );
}

function Tab({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`rounded-md px-4 py-2 text-center text-sm font-bold transition-colors ${
        active ? "bg-gold text-gold-ink" : "text-white hover:text-gold"
      }`}
    >
      {children}
    </Link>
  );
}
