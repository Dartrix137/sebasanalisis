"use client";

/**
 * Sesión del lado del cliente: guarda los tokens y el usuario, y renueva el
 * access token con el refresh cuando la API responde 401.
 *
 * Los tokens viven en localStorage. Es suficiente para el MVP; si más adelante
 * se endurece la seguridad, el cambio es mover el refresh a una cookie httpOnly
 * (§3.6 no lo exige todavía).
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

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

/** Margen para renovar antes de que el access token venza. */
const REFRESH_MARGIN_MS = 30_000;

/**
 * Cuánto dura el JWT (`exp - iat`), en ms, o null si no se puede leer. Solo
 * sirve para decidir cuándo renovar; la validez la decide el servidor.
 *
 * Se usa la duración y no `exp` contra el reloj del equipo: con un reloj
 * adelantado más que la vida del token, cada token recién emitido ya parecería
 * vencido y se renovaría sin fin.
 */
function lifetimeMs(token: string): number | null {
  try {
    const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const { exp, iat } = JSON.parse(atob(payload)) as { exp?: number; iat?: number };
    return typeof exp === "number" && typeof iat === "number" ? (exp - iat) * 1000 : null;
  } catch {
    return null;
  }
}

/** El mismo usuario conserva el mismo objeto: un objeto nuevo en cada
 * renovación haría correr de nuevo todo efecto que dependa de `user`. */
function keepIfSame(prev: UserResponse | null, next: UserResponse): UserResponse {
  return prev !== null && JSON.stringify(prev) === JSON.stringify(next) ? prev : next;
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
  // `withToken` lee los tokens de este ref para mantener su identidad estable:
  // si cambiara con cada renovación, todo efecto que dependa de él (la recarga
  // de la mesa, el panel de banca) volvería a correr entero.
  const storedRef = useRef(stored);
  storedRef.current = stored;
  // Cuándo llegó el access token vigente, según el reloj de este equipo. Con
  // su duración dice cuándo renovarlo sin comparar relojes con el servidor.
  const receivedAt = useRef(0);

  useEffect(() => {
    const s = read();
    if (!s) {
      setLoading(false);
      return;
    }
    // Uno leído del almacenamiento no dice cuándo llegó: se cuenta desde ahora
    // y, si ya había vencido, lo cubre el reintento tras el 401.
    receivedAt.current = Date.now();
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
          receivedAt.current = Date.now();
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
    storedRef.current = next;
    receivedAt.current = Date.now();
    setStored(next);
    setUser(tokens.user);
  }, []);

  const signOut = useCallback(() => {
    write(null);
    storedRef.current = null;
    setStored(null);
    setUser(null);
  }, []);

  // Una sola renovación en vuelo, compartida: la mesa lanza ~10 peticiones en
  // paralelo, y sin esto un token vencido provocaba ~10 renovaciones.
  const refreshing = useRef<Promise<StoredSession> | null>(null);

  const renew = useCallback((refreshToken: string): Promise<StoredSession> => {
    if (!refreshing.current) {
      refreshing.current = authApi
        .refresh({ refresh_token: refreshToken })
        .then((renewed) => {
          const next = {
            access_token: renewed.access_token,
            refresh_token: renewed.refresh_token,
          };
          write(next);
          storedRef.current = next;
          receivedAt.current = Date.now();
          setStored(next);
          setUser((prev) => keepIfSame(prev, renewed.user));
          return next;
        })
        .finally(() => {
          refreshing.current = null;
        });
    }
    return refreshing.current;
  }, []);

  const withToken = useCallback(
    async <T,>(fn: (token: string) => Promise<T>): Promise<T> => {
      let current = storedRef.current;
      if (!current) throw new ApiError(401, "No hay sesión activa");
      // Renovar antes de que venza ahorra la ronda de 401 y reintentos.
      const vida = lifetimeMs(current.access_token);
      const porVencer =
        vida !== null && Date.now() - receivedAt.current > vida - REFRESH_MARGIN_MS;
      if (refreshing.current || porVencer) {
        current = await renew(current.refresh_token);
      }
      try {
        return await fn(current.access_token);
      } catch (err) {
        if (!(err instanceof ApiError) || err.status !== 401) throw err;
        const next = await renew(current.refresh_token);
        return fn(next.access_token);
      }
    },
    [renew],
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
