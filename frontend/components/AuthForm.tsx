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

import { ApiError, authApi, legalApi } from "@/lib/api-client";
import { legalPath } from "@/lib/legal";
import { useSession } from "@/lib/session";
import type { LegalDocumentResponse } from "@/lib/types/legal";

import { PASSWORD_HINT, PASSWORD_MIN_LENGTH } from "./AuthShell";
import { BrandMark, Button, Card, Checkbox, ErrorBox, Field, PasswordField } from "./ui";

const SUBTITLE = "Registra los números de tu mesa y revisa lo que ya salió. Tu progreso queda guardado en tu cuenta.";

/** Cómo empieza la frase de cada casilla; el enlace al documento la termina. */
const CONSENT_LEAD: Partial<Record<LegalDocumentResponse["kind"], string>> = {
  terms: "Acepto los",
  privacy: "Autorizo el tratamiento de mis datos personales según la",
};

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const isRegister = mode === "register";
  const router = useRouter();
  const { signIn, user, loading } = useSession();

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  // Consentimientos del registro (§6.3): los documentos vigentes que hay que
  // aceptar, cuáles se marcaron, y la declaración de mayoría de edad.
  const [documents, setDocuments] = useState<LegalDocumentResponse[] | null>(null);
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});
  const [adult, setAdult] = useState(false);

  useEffect(() => {
    if (!isRegister) return;
    legalApi
      .required()
      .then(setDocuments)
      .catch(() =>
        setError("No se pudieron cargar los documentos legales. Recarga la página"),
      );
  }, [isRegister]);

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
            // Los ids de las versiones que se mostraron: la aceptación queda
            // atada al texto exacto. El servidor rechaza el registro si faltan.
            accepted_document_ids: (documents ?? []).filter((d) => accepted[d.id]).map((d) => d.id),
            adult_confirmed: adult,
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
    <main className="flex flex-1 flex-col items-center justify-center px-4 py-12">
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
            minLength={isRegister ? PASSWORD_MIN_LENGTH : undefined}
            autoComplete={isRegister ? "new-password" : "current-password"}
            hint={isRegister ? PASSWORD_HINT : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />

          {isRegister ? null : (
            <p className="-mt-1 text-right text-xs">
              <Link href="/olvide-contrasena" className="font-bold text-gold hover:text-gold-soft">
                ¿Olvidaste tu contraseña?
              </Link>
            </p>
          )}

          {isRegister ? (
            <fieldset className="space-y-3 border-t border-edge pt-4">
              <legend className="sr-only">Consentimientos</legend>
              {(documents ?? []).map((doc) => (
                <Checkbox
                  key={doc.id}
                  required
                  checked={!!accepted[doc.id]}
                  onChange={(e) => setAccepted((prev) => ({ ...prev, [doc.id]: e.target.checked }))}
                >
                  {CONSENT_LEAD[doc.kind] ?? "Acepto:"}{" "}
                  <a
                    href={legalPath(doc.kind)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-bold text-gold hover:text-gold-soft"
                  >
                    {doc.title}
                  </a>
                  .
                </Checkbox>
              ))}
              <Checkbox required checked={adult} onChange={(e) => setAdult(e.target.checked)}>
                Declaro que soy mayor de edad (18 años o más).
              </Checkbox>
            </fieldset>
          ) : null}

          {error ? <ErrorBox message={error} /> : null}

          <Button
            type="submit"
            disabled={pending || (isRegister && documents === null)}
            className="w-full"
          >
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
