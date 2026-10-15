import { expect, test } from "@playwright/test";

import { loginViaUi, registerViaApi, uniqueEmail } from "./helpers";

/**
 * Humo: iniciar sesión, abrir una mesa, registrar un giro y ver la tarjeta de
 * recomendación. Si esto falla, el producto no hace lo único que tiene que hacer.
 *
 * Cada test registra su propio usuario: no comparten estado.
 */

// Doce números: con menos de diez giros el motor todavía no recomienda.
const NUMEROS_INICIALES = "17, 32, 0, 15, 4, 21, 2, 25, 17, 34, 6, 27";

test("iniciar sesión, abrir una mesa, registrar un giro y ver la recomendación", async ({
  page,
  request,
}) => {
  const email = uniqueEmail();
  await registerViaApi(request, email);

  // Iniciar sesión por la pantalla.
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/dashboard/);

  // Abrir una mesa europea con carga inicial, declarando el orden.
  // Del menú de juegos a la página de la ruleta, y de ahí a la mesa.
  await page.getByRole("link", { name: "Jugar Ruleta" }).click();
  await expect(page).toHaveURL(/\/juegos\/ruleta$/);
  await page.getByRole("button", { name: /abrir mesa europea/i }).click();
  // Antes de abrir la mesa se dice cuántos números pide la primera recomendación.
  const aviso = page.getByTestId("aviso-minimo");
  await expect(aviso.getByText("al menos 11 números registrados")).toBeVisible();
  await expect(aviso.getByText(/mínimo que acepte la casa/)).toBeVisible();
  await page.getByRole("textbox", { name: /Números ya observados en la mesa/ }).fill("1 2 3");
  await expect(aviso.getByText("Con estos 3 te faltan 8.")).toBeVisible();
  await page.getByRole("textbox", { name: /Números ya observados en la mesa/ }).fill(NUMEROS_INICIALES);
  await page.getByLabel(/Del más antiguo al más reciente/).check();
  await page.getByRole("button", { name: "Empezar sesión" }).click();
  await expect(page).toHaveURL(/\/juegos\/ruleta\/mesa\/[0-9a-f-]+/);

  // La tarjeta de recomendación, con su línea fija obligatoria.
  const lineaFija = page.getByText(
    "Recomendación generada a partir del análisis estadístico de los resultados registrados. No es una predicción.",
  );
  await expect(page.getByText("Recomendación para el siguiente giro")).toBeVisible();
  await expect(lineaFija).toBeVisible();

  // Apostar al rojo por fuera de la recomendación y registrar un giro negro.
  await page.getByRole("button", { name: /^\+ Registrar (otra apuesta|una apuesta igual)$/ }).click();
  await page.getByLabel("Categoría").selectOption({ label: "Color" });
  await page.getByLabel("A qué apostaste").selectOption({ label: "Rojo · paga 1 a 1" });
  await page.getByLabel("Monto apostado").fill("1000");
  await page.getByRole("button", { name: "Registrar", exact: true }).click();
  await page.getByRole("button", { name: "8", exact: true }).click();
  await expect(page.getByText(/Perdiste .*1\.000 con el 8\b/)).toBeVisible();

  // Las apuestas de la sesión se cuentan por giro, con lo esperable al lado.
  await page.getByText("Apuestas de esta sesión").click();
  const cifras = page.getByTestId("estadisticas-apuestas");
  await expect(cifras.getByText("0 de 1 · 0.0 %")).toBeVisible();
  await expect(cifras.getByText("48.6 %")).toBeVisible();

  // Con trece giros el motor ya decide: recomienda una jugada o dice que no se apueste.
  await expect(
    page.getByRole("heading", { name: /^(APOSTAR: |NO APOSTAR ESTE GIRO)/ }),
  ).toBeVisible();
  await expect(lineaFija).toBeVisible();
});
