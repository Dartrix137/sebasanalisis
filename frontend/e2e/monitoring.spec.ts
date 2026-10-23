import { expect, test } from "@playwright/test";

import type { ErrorEvent } from "@sentry/nextjs";

import { scrubEvent, stripQuery } from "../lib/monitoring";

/**
 * El filtro de lo que el frontend envía al monitoreo (§13.6). Es una función
 * pura: se prueba aquí, sin navegador, porque el frontend no tiene otro
 * corredor de tests.
 */

const TOKEN = "tok3n-de-un-solo-uso";

function event(overrides: Partial<ErrorEvent>): ErrorEvent {
  return { type: undefined, ...overrides };
}

test("stripQuery deja la URL sin parámetros ni fragmento", () => {
  expect(stripQuery(`https://sebasanalisis.com/verificar-correo?token=${TOKEN}`)).toBe(
    "https://sebasanalisis.com/verificar-correo",
  );
  expect(stripQuery(`/restablecer-contrasena#token=${TOKEN}`)).toBe("/restablecer-contrasena");
  expect(stripQuery("https://api.sebasanalisis.com/games")).toBe(
    "https://api.sebasanalisis.com/games",
  );
});

test("un error en la página de un enlace de correo no envía el token", () => {
  const limpio = scrubEvent(
    event({
      request: {
        url: `https://sebasanalisis.com/restablecer-contrasena?token=${TOKEN}`,
        query_string: `token=${TOKEN}`,
        headers: {
          "User-Agent": "Mozilla/5.0",
          Referer: `https://sebasanalisis.com/verificar-correo?token=${TOKEN}`,
        },
      },
      breadcrumbs: [
        {
          category: "navigation",
          data: { from: "/login", to: `/verificar-correo?token=${TOKEN}` },
        },
        {
          category: "fetch",
          data: {
            url: `https://sebasanalisis.com/verificar-correo?token=${TOKEN}&_rsc=abc`,
            method: "GET",
            status_code: 200,
          },
        },
        { category: "ui.click", message: "button" },
      ],
    }),
  );

  expect(JSON.stringify(limpio)).not.toContain(TOKEN);
  expect(limpio.request?.url).toBe("https://sebasanalisis.com/restablecer-contrasena");
  expect(limpio.request?.headers?.["User-Agent"]).toBe("Mozilla/5.0");
  expect(limpio.breadcrumbs?.[0].data).toEqual({ from: "/login", to: "/verificar-correo" });
  expect(limpio.breadcrumbs?.[1].data).toEqual({
    url: "https://sebasanalisis.com/verificar-correo",
    method: "GET",
    status_code: 200,
  });
});

test("las cabeceras de autenticación, las cookies y los cuerpos no salen", () => {
  const limpio = scrubEvent(
    event({
      request: {
        url: "https://sebasanalisis.com/cuenta",
        headers: { Authorization: "Bearer secreto", Cookie: "a=secreto" },
        cookies: { a: "secreto" },
        data: { password: "secreto" },
      },
    }),
  );

  expect(JSON.stringify(limpio)).not.toContain("secreto");
  expect(limpio.request?.headers).toEqual({
    Authorization: "[filtrado]",
    Cookie: "[filtrado]",
  });
  expect(limpio.request?.cookies).toBeUndefined();
});

test("un evento sin petición pasa sin cambios", () => {
  const original = event({ message: "prueba" });
  expect(scrubEvent(original)).toEqual({ type: undefined, message: "prueba" });
});
