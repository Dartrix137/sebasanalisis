"use client";

/**
 * Compuerta de las pantallas de juego (§6.3 de la Fase 4).
 *
 * Antes de montar la pantalla pregunta a la API qué le falta aceptar a la
 * cuenta. Si hay algo —un documento vigente sin aceptar o la declaración de
 * mayoría de edad—, muestra la pantalla de aceptación en lugar del contenido.
 * Con `onboarding`, además muestra una vez la pantalla que explica qué hace y
 * qué no hace la plataforma.
 *
 * Esto es presentación, no control de acceso: quien decide es el servidor, que
 * responde `403 consent_required` en todos los endpoints de juego. La compuerta
 * solo evita mostrar una mesa llena de errores.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { ApiError, authApi, legalApi } from "@/lib/api-client";
import { formatLegalDate, legalPath } from "@/lib/legal";
import { useSession } from "@/lib/session";
import type { LegalDocumentResponse, PendingConsentResponse } from "@/lib/types/legal";

import { BrandMark, Button, Card, Checkbox, ErrorBox } from "../ui";
import { Markdown } from "./Markdown";

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.message : "No se pudo completar la solicitud";
}

export function LegalGate({
  children,
  onboarding = false,
}: {
  children: ReactNode;
  /** Muestra la pantalla de bienvenida si la cuenta no la ha leído. */
  onboarding?: boolean;
}) {
  const { user, loading, withToken } = useSession();
  const router = useRouter();
  const [pending, setPending] = useState<PendingConsentResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const userId = user?.id ?? null;

  useEffect(() => {
    if (loading) return;
    if (!userId) {
      router.replace("/login");
      return;
    }
    withToken((t) => legalApi.pending(t))
      .then(setPending)
      .catch((e) => setError(messageOf(e)));
  }, [loading, userId, router, withToken]);

  if (loading || !user) return null;
  if (error && !pending) {
    return (
      <Shell title="No se pudo continuar">
        <ErrorBox message={error} />
      </Shell>
    );
  }
  if (!pending) return null;

  if (pending.documents.length > 0 || pending.adult_confirmation_required) {
    return <ConsentScreen pending={pending} onAccepted={setPending} />;
  }
  if (onboarding && !user.onboarding_completed_at) return <OnboardingScreen />;
  return <>{children}</>;
}

function Shell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  const { signOut } = useSession();
  const router = useRouter();
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-4 pb-12 pt-10 sm:px-6">
      <div className="flex items-center justify-between gap-3">
        <BrandMark size={38} />
        <div className="flex items-center gap-4 text-sm">
          {/* La cuenta nunca queda bloqueada: se puede revisar o eliminar. */}
          <Link href="/cuenta" className="font-bold text-gold hover:text-gold-soft">
            Mi cuenta
          </Link>
          <button
            type="button"
            className="font-bold text-muted hover:text-white"
            onClick={() => {
              signOut();
              router.replace("/login");
            }}
          >
            Salir
          </button>
        </div>
      </div>
      <h1 className="mt-8 font-display text-4xl font-semibold leading-none tracking-tight">
        {title}
      </h1>
      {subtitle ? (
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-muted">{subtitle}</p>
      ) : null}
      <div className="mt-6 space-y-5">{children}</div>
    </main>
  );
}

function ConsentScreen({
  pending,
  onAccepted,
}: {
  pending: PendingConsentResponse;
  onAccepted: (next: PendingConsentResponse) => void;
}) {
  const { withToken, refreshUser } = useSession();
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [adult, setAdult] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const complete =
    pending.documents.every((d) => checked[d.id]) &&
    (!pending.adult_confirmation_required || adult);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSending(true);
    try {
      const next = await withToken((t) =>
        legalApi.accept(t, {
          legal_document_ids: pending.documents.map((d) => d.id),
          adult_confirmed: pending.adult_confirmation_required && adult,
        }),
      );
      await refreshUser();
      onAccepted(next);
    } catch (err) {
      setError(messageOf(err));
      // 409: se publicó otra versión mientras se leía esta. Se trae la nueva.
      if (err instanceof ApiError && err.status === 409) {
        setChecked({});
        withToken((t) => legalApi.pending(t))
          .then(onAccepted)
          .catch(() => undefined);
      }
    } finally {
      setSending(false);
    }
  }

  return (
    <Shell
      title="Antes de continuar"
      subtitle="Para usar la mesa necesitas aceptar la versión vigente de estos documentos. Léelos y marca cada casilla."
    >
      <form onSubmit={handleSubmit} className="space-y-5">
        {pending.documents.map((doc) => (
          <ConsentDocument
            key={doc.id}
            document={doc}
            checked={!!checked[doc.id]}
            onChange={(value) => setChecked((prev) => ({ ...prev, [doc.id]: value }))}
          />
        ))}

        {pending.adult_confirmation_required ? (
          <Card>
            <Checkbox checked={adult} onChange={(e) => setAdult(e.target.checked)}>
              Declaro que soy mayor de edad (18 años o más).
            </Checkbox>
          </Card>
        ) : null}

        {error ? <ErrorBox message={error} /> : null}

        <Button type="submit" disabled={!complete || sending} className="w-full sm:w-auto">
          {sending ? "Un momento…" : "Aceptar y continuar"}
        </Button>
      </form>
    </Shell>
  );
}

function ConsentDocument({
  document,
  checked,
  onChange,
}: {
  document: LegalDocumentResponse;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <Card>
      <header className="mb-3">
        <h2 className="text-base font-bold text-white">{document.title}</h2>
        <p className="mt-1 text-xs text-muted">
          Versión {document.version} · Publicada el {formatLegalDate(document.published_at)} ·{" "}
          <a
            href={legalPath(document.kind)}
            target="_blank"
            rel="noopener noreferrer"
            className="font-bold text-gold hover:text-gold-soft"
          >
            Abrir en otra pestaña
          </a>
        </p>
      </header>
      <div
        tabIndex={0}
        role="region"
        aria-label={document.title}
        className="max-h-72 overflow-y-auto rounded-lg border border-edge bg-ink px-4 pb-4 pt-1"
      >
        <Markdown>{document.content_md}</Markdown>
      </div>
      <div className="mt-4">
        <Checkbox checked={checked} onChange={(e) => onChange(e.target.checked)}>
          He leído y acepto: {document.title} (versión {document.version}).
        </Checkbox>
      </div>
    </Card>
  );
}

/**
 * Bienvenida de la mesa, con scroll-to-accept (§0 del documento de
 * arquitectura): el botón se habilita al llegar al final del texto.
 */
function OnboardingScreen() {
  const { withToken, updateUser } = useSession();
  const box = useRef<HTMLDivElement>(null);
  const [reachedEnd, setReachedEnd] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const check = useCallback(() => {
    const el = box.current;
    if (el && el.scrollTop + el.clientHeight >= el.scrollHeight - 8) setReachedEnd(true);
  }, []);

  // En una pantalla alta el texto puede caber entero: no hay nada que desplazar.
  useEffect(() => {
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, [check]);

  async function handleContinue() {
    setError(null);
    setSending(true);
    try {
      updateUser(await withToken((t) => authApi.completeOnboarding(t)));
    } catch (err) {
      setError(messageOf(err));
      setSending(false);
    }
  }

  return (
    <Shell
      title="Qué hace y qué no hace Sebasanálisis"
      subtitle="Léelo hasta el final antes de entrar a la mesa. Solo se muestra esta vez."
    >
      <div
        ref={box}
        onScroll={check}
        tabIndex={0}
        role="region"
        aria-label="Qué hace y qué no hace Sebasanálisis"
        data-testid="onboarding-texto"
        className="max-h-[55vh] space-y-6 overflow-y-auto rounded-card border border-edge bg-ink-raised p-5 text-sm leading-relaxed text-muted"
      >
        <OnboardingBlock title="Lo que hace">
          <li>Guarda los números de la mesa que tú registras, uno por uno.</li>
          <li>
            Compara lo que ya salió con lo que se esperaría por probabilidad: frecuencias y
            desviaciones observadas.
          </li>
          <li>
            Después de cada número te entrega una recomendación para el siguiente giro: qué
            apostar, o no apostar, con un Signal Score de 0 a 100.
          </li>
          <li>
            Te muestra cuánto pediría cada gestión de banca (plana, martingala, dos sectores)
            para esa jugada.
          </li>
        </OnboardingBlock>

        <OnboardingBlock title="Lo que no hace">
          <li>
            <strong className="text-white">La recomendación no es una predicción.</strong> Sale
            de reglas estadísticas sobre resultados que ya ocurrieron. La plataforma no conoce el
            resultado del siguiente giro.
          </li>
          <li>
            <strong className="text-white">Cada giro es independiente.</strong> Lo que salió antes
            no cambia la probabilidad de lo que sale después.
          </li>
          <li>
            <strong className="text-white">
              El Signal Score es la fuerza del criterio interno, no la probabilidad de acertar.
            </strong>{" "}
            Un puntaje alto no hace más probable la jugada recomendada.
          </li>
          <li>
            <strong className="text-white">
              Ninguna gestión de banca cambia la ventaja de la casa.
            </strong>{" "}
            Solo define el tamaño de las apuestas, y una progresión puede pedir montos altos en
            pocas jugadas.
          </li>
          <li>
            Sebasanálisis no es un operador de juegos de azar: no recibe apuestas ni paga premios.
            Si juegas, lo haces por tu cuenta en un operador autorizado.
          </li>
        </OnboardingBlock>

        <OnboardingBlock title="Lo que depende de ti">
          <li>
            Los números los ingresas tú. Un número mal escrito o una lista cargada en el orden
            equivocado cambia el análisis sin que la plataforma lo note.
          </li>
          <li>Define tu banca y tu límite de pérdida antes de empezar, no durante la partida.</li>
          <li>
            Puedes perder dinero. Apostar o no, cuánto y dónde es una decisión únicamente tuya.
          </li>
          <li>El servicio es solo para mayores de edad.</li>
        </OnboardingBlock>
      </div>

      {error ? <ErrorBox message={error} /> : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={handleContinue} disabled={!reachedEnd || sending}>
          {sending ? "Un momento…" : "Entendido, continuar"}
        </Button>
        {reachedEnd ? null : (
          <p className="text-xs text-muted">Desplázate hasta el final del texto para continuar.</p>
        )}
      </div>
    </Shell>
  );
}

function OnboardingBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="font-display text-2xl font-semibold leading-tight text-white">{title}</h2>
      <ul className="mt-2 list-disc space-y-2 pl-5">{children}</ul>
    </section>
  );
}
