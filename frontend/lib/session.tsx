"use client";

/**
 * Sesión del lado del cliente: guarda los tokens y el usuario, y renueva el
 * access token con el refresh cuando la API responde 401.
 *
 * Los tokens viven en localStorage. Es suficiente para el MVP; si más adelante
 * se endurece la seguridad, el cambio es mover el refresh a una cookie httpOnly
 * (§3.6 no lo exige todavía).
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { ApiError, authApi } from "./api-client";
import type { TokenResponse, UserResponse } from "./types/auth";

const STORAGE_KEY = "sebasanalisis.session";

interface StoredSession {
  access_token: string;
  refresh_token: string;
}

interface SessionValue {
  user: UserResponse | null;
  token: string | null;
  loading: boolean;
  signIn: (tokens: TokenResponse) => void;
  signOut: () => void;
  /** Ejecuta una llamada y reintenta una vez si el access token expiró. */
  withToken: <T>(fn: (token: string) => Promise<T>) => Promise<T>;
}

const SessionContext = createContext<SessionValue | null>(null);

function read(): StoredSession | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as StoredSession) : null;
  } catch {
    return null;
  }
}

function write(value: StoredSession | null): void {
  try {
    if (value) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Almacenamiento bloqueado (modo privado): la sesión dura lo que la pestaña.
  }
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [stored, setStored] = useState<StoredSession | null>(null);
  const [user, setUser] = useState<UserResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const s = read();
    if (!s) {
      setLoading(false);
      return;
    }
    setStored(s);
    authApi
      .me(s.access_token)
      .then(setUser)
      .catch(async () => {
        try {
          const renewed = await authApi.refresh({ refresh_token: s.refresh_token });
          const next = {
            access_token: renewed.access_token,
            refresh_token: renewed.refresh_token,
          };
          write(next);
          setStored(next);
          setUser(renewed.user);
        } catch {
          write(null);
          setStored(null);
          setUser(null);
        }
      })
      .finally(() => setLoading(false));
  }, []);

  const signIn = useCallback((tokens: TokenResponse) => {
    const next = { access_token: tokens.access_token, refresh_token: tokens.refresh_token };
    write(next);
    setStored(next);
    setUser(tokens.user);
  }, []);

  const signOut = useCallback(() => {
    write(null);
    setStored(null);
    setUser(null);
  }, []);

  const withToken = useCallback(
    async <T,>(fn: (token: string) => Promise<T>): Promise<T> => {
      if (!stored) throw new ApiError(401, "No hay sesión activa");
      try {
        return await fn(stored.access_token);
      } catch (err) {
        if (!(err instanceof ApiError) || err.status !== 401) throw err;
        const renewed = await authApi.refresh({ refresh_token: stored.refresh_token });
        const next = {
          access_token: renewed.access_token,
          refresh_token: renewed.refresh_token,
        };
        write(next);
        setStored(next);
        setUser(renewed.user);
        return fn(next.access_token);
      }
    },
    [stored],
  );

  const value = useMemo<SessionValue>(
    () => ({ user, token: stored?.access_token ?? null, loading, signIn, signOut, withToken }),
    [user, stored, loading, signIn, signOut, withToken],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession debe usarse dentro de <SessionProvider>");
  return ctx;
}
