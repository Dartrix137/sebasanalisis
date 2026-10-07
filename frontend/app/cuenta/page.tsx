"use client";

/**
 * Mi cuenta: perfil, correo y seguridad (§5.4 de la Fase 4).
 *
 * La suscripción, el método de pago, el historial de pagos y los documentos
 * aceptados se suman en sus pasos (2 y 5).
 */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { PASSWORD_HINT, PASSWORD_MIN_LENGTH, SuccessBox } from "@/components/AuthShell";
import { Badge, Button, Card, CardHeader, ErrorBox, Field, PasswordField } from "@/components/ui";
import { ApiError, authApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";
import { useResendVerification } from "@/lib/useResendVerification";

type Outcome = { ok: boolean; message: string } | null;

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.message : "No se pudo completar la solicitud";
}

function OutcomeBox({ outcome }: { outcome: Outcome }) {
  if (!outcome) return null;
  return outcome.ok ? (
    <SuccessBox message={outcome.message} />
  ) : (
    <ErrorBox message={outcome.message} />
  );
}

export default function AccountPage() {
  const { user, loading } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading || !user) return null;

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-2xl space-y-5 px-4 pb-12 pt-8 sm:px-6">
        <h1 className="font-display text-4xl font-semibold leading-none tracking-tight">
          Mi cuenta
        </h1>
        <ProfileCard />
        <EmailCard />
        <PasswordCard />
        <DeleteAccountCard />
      </main>
    </div>
  );
}

function ProfileCard() {
  const { user, withToken, updateUser } = useSession();
  const [name, setName] = useState(user?.display_name ?? "");
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setOutcome(null);
    setPending(true);
    try {
      const next = await withToken((t) =>
        authApi.updateProfile(t, { display_name: name.trim() || null }),
      );
      updateUser(next);
      setName(next.display_name ?? "");
      setOutcome({ ok: true, message: "Nombre guardado" });
    } catch (err) {
      setOutcome({ ok: false, message: messageOf(err) });
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Perfil" subtitle="El nombre con el que te saluda la aplicación." />
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field
          label="Tu nombre"
          placeholder="Ej: Carlos"
          autoComplete="name"
          maxLength={100}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <OutcomeBox outcome={outcome} />
        <Button type="submit" disabled={pending}>
          {pending ? "Guardando…" : "Guardar nombre"}
        </Button>
      </form>
    </Card>
  );
}

function EmailCard() {
  const { user, withToken } = useSession();
  const {
    resend,
    pending: resending,
    secondsLeft: resendSecondsLeft,
    outcome: resent,
  } = useResendVerification();

  const [newEmail, setNewEmail] = useState("");
  const [password, setPassword] = useState("");
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [pending, setPending] = useState(false);

  if (!user) return null;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setOutcome(null);
    setPending(true);
    try {
      const { message } = await withToken((t) =>
        authApi.changeEmail(t, { new_email: newEmail, password }),
      );
      setNewEmail("");
      setPassword("");
      setOutcome({ ok: true, message });
    } catch (err) {
      setOutcome({ ok: false, message: messageOf(err) });
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Correo" />
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-bold text-white">{user.email}</span>
        {user.email_verified ? (
          <Badge tone="ok">Confirmado</Badge>
        ) : (
          <Badge tone="off">Sin confirmar</Badge>
        )}
      </div>

      {user.email_verified ? null : (
        <div className="mt-3 space-y-3">
          <p className="text-sm leading-relaxed text-muted">
            Te enviamos un enlace de confirmación al registrarte. Si no lo ves en tu bandeja de
            entrada, revisa la carpeta de correo no deseado. Si tampoco está ahí, pide uno nuevo; el
            anterior deja de servir.
          </p>
          <OutcomeBox outcome={resent} />
          <Button
            variant="ghost"
            onClick={resend}
            disabled={resending || resendSecondsLeft > 0}
          >
            {resending
              ? "Enviando…"
              : resendSecondsLeft > 0
                ? `Reenviar en ${resendSecondsLeft} s`
                : "Reenviar correo de confirmación"}
          </Button>
        </div>
      )}

      <form onSubmit={handleSubmit} className="mt-6 space-y-4 border-t border-edge pt-5">
        <h3 className="text-sm font-bold text-white">Cambiar de correo</h3>
        <p className="text-sm leading-relaxed text-muted">
          Te enviamos un enlace al correo nuevo. El cambio se aplica cuando lo confirmes; hasta
          entonces sigues entrando con el actual. Si el enlace no llega, revisa la carpeta de correo
          no deseado.
        </p>
        <Field
          label="Correo nuevo"
          type="email"
          required
          autoComplete="email"
          placeholder="nuevo@ejemplo.com"
          value={newEmail}
          onChange={(e) => setNewEmail(e.target.value)}
        />
        <PasswordField
          id="change-email-password"
          label="Tu contraseña"
          required
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <OutcomeBox outcome={outcome} />
        <Button type="submit" disabled={pending}>
          {pending ? "Un momento…" : "Cambiar correo"}
        </Button>
      </form>
    </Card>
  );
}

function PasswordCard() {
  const { withToken, signIn } = useSession();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setOutcome(null);
    setPending(true);
    try {
      const tokens = await withToken((t) =>
        authApi.changePassword(t, { current_password: current, new_password: next }),
      );
      // Los tokens anteriores ya no valen: esta sesión sigue con los nuevos.
      signIn(tokens);
      setCurrent("");
      setNext("");
      setOutcome({
        ok: true,
        message: "Contraseña cambiada. Se cerraron las demás sesiones abiertas de tu cuenta",
      });
    } catch (err) {
      setOutcome({ ok: false, message: messageOf(err) });
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Contraseña"
        subtitle="Al cambiarla se cierran las sesiones abiertas en tus otros dispositivos."
      />
      <form onSubmit={handleSubmit} className="space-y-4">
        <PasswordField
          id="current-password"
          label="Contraseña actual"
          required
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
        <PasswordField
          id="next-password"
          label="Contraseña nueva"
          required
          minLength={PASSWORD_MIN_LENGTH}
          autoComplete="new-password"
          hint={PASSWORD_HINT}
          value={next}
          onChange={(e) => setNext(e.target.value)}
        />
        <OutcomeBox outcome={outcome} />
        <Button type="submit" disabled={pending}>
          {pending ? "Un momento…" : "Cambiar contraseña"}
        </Button>
      </form>
    </Card>
  );
}

function DeleteAccountCard() {
  const { withToken, signOut } = useSession();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      await withToken((t) => authApi.deleteAccount(t, { password }));
      signOut();
      router.replace("/login");
    } catch (err) {
      setError(messageOf(err));
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Eliminar cuenta"
        subtitle="Borra tu perfil, tus mesas, los números que registraste y tus apuestas anotadas. No se puede deshacer."
      />
      {open ? (
        <form onSubmit={handleSubmit} className="space-y-4">
          <PasswordField
            id="delete-account-password"
            label="Escribe tu contraseña para confirmar"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error ? <ErrorBox message={error} /> : null}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="danger" disabled={pending}>
              {pending ? "Eliminando…" : "Eliminar definitivamente"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setOpen(false);
                setPassword("");
                setError(null);
              }}
            >
              Cancelar
            </Button>
          </div>
        </form>
      ) : (
        <Button variant="danger" onClick={() => setOpen(true)}>
          Eliminar mi cuenta
        </Button>
      )}
    </Card>
  );
}
