"use client";

/**
 * Verificación contra bots (Cloudflare Turnstile) en el registro, el ingreso y
 * el olvido de contraseña. El widget entrega un token de un solo uso que el
 * servidor valida contra Cloudflare (`backend/app/core/bot_check.py`).
 *
 * La llave del sitio la entrega la API (`GET /auth/bot-check`). Si responde
 * `null`, la verificación está apagada: no se dibuja nada y el formulario envía
 * sin token. Así se configura en un solo lugar, sin argumento de build.
 *
 * Script y opciones, de la documentación oficial de Cloudflare (2026-10-20):
 * https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/
 * https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/widget-configurations/
 * El script se carga desde su URL exacta (no se copia ni se sirve desde aquí) y
 * lo inserta este código, así que la CSP con `strict-dynamic` lo deja correr.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { authApi } from "@/lib/api-client";

const SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

interface TurnstileOptions {
  sitekey: string;
  action: string;
  theme: "light" | "dark" | "auto";
  language: string;
  callback: (token: string) => void;
  "expired-callback": () => void;
  "error-callback": () => void;
}

interface Turnstile {
  render: (container: HTMLElement, options: TurnstileOptions) => string;
  reset: (widgetId: string) => void;
  remove: (widgetId: string) => void;
}

declare global {
  interface Window {
    turnstile?: Turnstile;
  }
}

let scriptPromise: Promise<Turnstile> | null = null;

/** Carga el script una sola vez por página, aunque haya varios formularios. */
function loadTurnstile(): Promise<Turnstile> {
  if (window.turnstile) return Promise.resolve(window.turnstile);
  if (!scriptPromise) {
    scriptPromise = new Promise<Turnstile>((resolve, reject) => {
      const script = document.createElement("script");
      script.src = SCRIPT_URL;
      script.async = true;
      script.onload = () =>
        window.turnstile ? resolve(window.turnstile) : reject(new Error("Turnstile no cargó"));
      script.onerror = () => {
        scriptPromise = null;
        reject(new Error("Turnstile no cargó"));
      };
      document.head.appendChild(script);
    });
  }
  return scriptPromise;
}

export interface BotCheck {
  /** Lo que va en el formulario, encima del botón. `null` si está apagada. */
  widget: ReactNode;
  /** El token para `bot_check_token`, o `undefined` si no hay que mandar nada. */
  token: string | undefined;
  /** Si el botón tiene que esperar: la verificación está encendida y sin token. */
  waiting: boolean;
  /** Pide un token nuevo: cada uno sirve una sola vez, también si el envío falló. */
  reset: () => void;
}

/** `action`: el formulario, igual que lo espera el servidor (`login`, `register`…). */
export function useBotCheck(action: "login" | "register" | "forgot-password"): BotCheck {
  // undefined: todavía no se sabe; null: apagada.
  const [siteKey, setSiteKey] = useState<string | null | undefined>(undefined);
  const [token, setToken] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const widgetId = useRef<string | null>(null);

  useEffect(() => {
    let vigente = true;
    authApi
      .botCheck()
      .then((r) => vigente && setSiteKey(r.site_key))
      // Sin respuesta se envía sin token: si estaba encendida, el servidor lo dice.
      .catch(() => vigente && setSiteKey(null));
    return () => {
      vigente = false;
    };
  }, []);

  useEffect(() => {
    if (!siteKey || !container.current) return;
    const target = container.current;
    let vigente = true;
    loadTurnstile()
      .then((turnstile) => {
        if (!vigente) return;
        widgetId.current = turnstile.render(target, {
          sitekey: siteKey,
          action,
          theme: "dark",
          language: "es",
          callback: (t) => {
            setFailed(false);
            setToken(t);
          },
          "expired-callback": () => setToken(null),
          "error-callback": () => {
            setToken(null);
            setFailed(true);
          },
        });
      })
      .catch(() => vigente && setFailed(true));
    return () => {
      vigente = false;
      if (widgetId.current && window.turnstile) window.turnstile.remove(widgetId.current);
      widgetId.current = null;
    };
  }, [siteKey, action]);

  const reset = useCallback(() => {
    setToken(null);
    if (widgetId.current && window.turnstile) window.turnstile.reset(widgetId.current);
  }, []);

  const widget =
    siteKey === null ? null : (
      <div>
        {/* Alto fijo: el widget de Cloudflare no hace saltar el formulario al aparecer. */}
        <div ref={container} className="min-h-[65px]" data-testid="bot-check" />
        {failed ? (
          <p className="mt-1 text-xs font-bold text-table-red">
            No pudimos cargar la verificación. Revisa tu conexión y recarga la página.
          </p>
        ) : null}
      </div>
    );

  return {
    widget,
    token: token ?? undefined,
    waiting: siteKey !== null && token === null,
    reset,
  };
}
