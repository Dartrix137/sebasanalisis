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
  await page.getByRole("button", { name: /abrir mesa europea/i }).click();
  await page.getByPlaceholder("17, 32, 0, 15, 4").fill(NUMEROS_INICIALES);
  await page.getByLabel(/Del más antiguo al más reciente/).check();
  await page.getByRole("button", { name: "Empezar sesión" }).click();
  await expect(page).toHaveURL(/\/games\/roulette\/[0-9a-f-]+/);

  // La tarjeta de recomendación, con su línea fija obligatoria.
  const lineaFija = page.getByText(
    "Recomendación generada a partir del análisis estadístico de los resultados registrados. No es una predicción.",
  );
  await expect(page.getByText("Recomendación para el siguiente giro")).toBeVisible();
  await expect(lineaFija).toBeVisible();

  // Registrar un giro.
  await page.getByRole("button", { name: "8", exact: true }).click();
  await expect(page.getByText(/Salió el 8\b/)).toBeVisible();

  // Con trece giros el motor ya decide: recomienda una jugada o dice que no se apueste.
  await expect(
    page.getByRole("heading", { name: /^(APOSTAR: |NO APOSTAR ESTE GIRO)/ }),
  ).toBeVisible();
  await expect(lineaFija).toBeVisible();
});
