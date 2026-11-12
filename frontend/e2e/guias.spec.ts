import { expect, test } from "@playwright/test";

import { API_URL, loginViaUi, registerViaApi, uniqueEmail } from "./helpers";

/**
 * Guías de la ruleta (2026-11-12): la ventana sale una sola vez en el inicio, y
 * después los videos y el PDF siguen en `/juegos/ruleta/guias`.
 *
 * La API de los tests corre con `GUIDES_ENABLED=false` (`start-api.mjs`), así que
 * aquí se simula la respuesta de las guías. YouTube no se carga: su marco se
 * responde con una página vacía, para no salir a la red.
 */

const GUIAS = {
  videos: [
    { title: "Parte 1", youtube_id: "AbCdEfGhIj1" },
    { title: "Parte 2", youtube_id: "AbCdEfGhIj2" },
  ],
  pdf: {
    title: "la guía (PDF)",
    url: "https://res.cloudinary.com/demo/image/upload/fl_attachment/guia.pdf",
  },
};

test("la ventana de las guías sale una vez y después quedan en Guías", async ({
  page,
  request,
}) => {
  await page.route(`${API_URL}/games/*/guides`, (route) => route.fulfill({ json: GUIAS }));
  await page.route("https://www.youtube-nocookie.com/**", (route) =>
    route.fulfill({ contentType: "text/html", body: "<!doctype html><title>video</title>" }),
  );

  const email = uniqueEmail();
  await registerViaApi(request, email, { guias: "pendiente" });
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/dashboard/);

  // La ventana: el primer video, el paso al segundo y el PDF.
  const ventana = page.getByTestId("guias-ventana");
  await expect(ventana).toBeVisible();
  await expect(ventana.getByText("Video 1 de 2: Parte 1")).toBeVisible();
  await expect(ventana.locator('iframe[src*="youtube-nocookie.com/embed/AbCdEfGhIj1"]')).toBeAttached();
  await ventana.getByRole("button", { name: "Siguiente: Parte 2" }).click();
  await expect(ventana.getByText("Video 2 de 2: Parte 2")).toBeVisible();
  await expect(ventana.locator('iframe[src*="youtube-nocookie.com/embed/AbCdEfGhIj2"]')).toBeAttached();
  await expect(ventana.getByTestId("guia-pdf")).toHaveAttribute("href", GUIAS.pdf.url);

  // Al cerrarla queda anotada en el servidor y no vuelve a salir.
  const anotada = page.waitForResponse(
    (r) => r.url().endsWith("/auth/me/guides-seen") && r.request().method() === "POST",
  );
  await ventana.getByRole("button", { name: "Cerrar" }).click();
  expect((await anotada).ok()).toBeTruthy();
  await expect(ventana).toBeHidden();
  await page.reload();
  await expect(page.getByRole("heading", { name: /^Hola/ })).toBeVisible();
  await expect(page.getByTestId("guias-ventana")).toHaveCount(0);

  // Siguen en el apartado "Guías" de la ruleta.
  await page.getByRole("link", { name: "Jugar Ruleta" }).click();
  await page.getByTestId("guias-enlace").click();
  await expect(page).toHaveURL(/\/juegos\/ruleta\/guias$/);
  await expect(page.getByRole("heading", { name: "Parte 1" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Parte 2" })).toBeVisible();
  await expect(page.locator('iframe[src*="youtube-nocookie.com/embed/"]')).toHaveCount(2);
  await expect(page.getByTestId("guia-pdf")).toHaveAttribute("href", GUIAS.pdf.url);
});

test("con las guías ya vistas, el inicio no muestra la ventana", async ({ page, request }) => {
  await page.route(`${API_URL}/games/*/guides`, (route) => route.fulfill({ json: GUIAS }));
  const email = uniqueEmail();
  await registerViaApi(request, email);
  await loginViaUi(page, email);
  await expect(page.getByRole("heading", { name: /^Hola/ })).toBeVisible();
  await expect(page.getByTestId("guias-ventana")).toHaveCount(0);
});
