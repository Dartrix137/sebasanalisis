import { expect, test } from "@playwright/test";

import {
  checkRegisterConsents,
  loginViaUi,
  PASSWORD,
  registerViaApi,
  uniqueEmail,
} from "./helpers";

/**
 * Flujos legales del paso 2 de la Fase 4 (§6): un error aquí es una cuenta
 * creada sin consentimientos o un documento que el público no puede leer.
 */

test("página legal pública: versión vigente, con su fecha y el aviso de borrador", async ({
  page,
}) => {
  await page.goto("/legal/terminos");

  await expect(page.getByRole("heading", { level: 1, name: "Términos y Condiciones" })).toBeVisible();
  await expect(page.getByText(/Versión \d+ · Publicada el \d+ de \w+ de \d{4}/)).toBeVisible();
  await expect(page.getByText(/BORRADOR — pendiente de revisión por un abogado/)).toBeVisible();
  // El contenido mínimo de §6.5 está a la vista, sin sesión.
  await expect(page.getByText("La recomendación no es una predicción.")).toBeVisible();
  await expect(
    page.getByText("Sebasanálisis no es un operador de juegos de suerte y azar."),
  ).toBeVisible();

  // Desde el pie se llega a los demás documentos.
  const pie = page.getByRole("navigation", { name: "Documentos legales" });
  await pie.getByRole("link", { name: "Tratamiento de datos" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Política de Tratamiento de Datos Personales" }),
  ).toBeVisible();
  await expect(page.getByText(/último número en cero/)).toBeVisible();

  await page.goto("/legal/no-existe");
  await expect(page.getByText(/404/)).toBeVisible();
});

test("el pie con los documentos legales está en login y en registro", async ({ page }) => {
  for (const ruta of ["/login", "/register"]) {
    await page.goto(ruta);
    const pie = page.getByRole("navigation", { name: "Documentos legales" });
    for (const nombre of [
      "Términos y Condiciones",
      "Tratamiento de datos",
      "Cancelación y reembolsos",
      "Cookies",
    ]) {
      await expect(pie.getByRole("link", { name: nombre })).toBeVisible();
    }
  }
});

test("registro: sin las casillas no se crea la cuenta; con ellas, sí", async ({ page }) => {
  const email = uniqueEmail();

  await page.goto("/register");
  await page.getByLabel("Correo electrónico").fill(email);
  await page.locator("#password").fill(PASSWORD);

  // Las casillas enlazan al documento que se acepta.
  await expect(page.getByRole("link", { name: "Términos y Condiciones" }).first()).toHaveAttribute(
    "href",
    "/legal/terminos",
  );

  // Sin marcar nada, el formulario no se envía.
  await page.getByRole("button", { name: "Crear mi cuenta" }).click();
  await expect(page).toHaveURL(/\/register/);

  // Con dos de tres tampoco.
  await page.getByRole("checkbox", { name: /Acepto los Términos y Condiciones/ }).check();
  await page.getByRole("checkbox", { name: /Declaro que soy mayor de edad/ }).check();
  await page.getByRole("button", { name: "Crear mi cuenta" }).click();
  await expect(page).toHaveURL(/\/register/);

  await checkRegisterConsents(page);
  await page.getByRole("button", { name: "Crear mi cuenta" }).click();
  // Una cuenta nueva nace sin acceso: la mesa la manda a los planes.
  await expect(page).toHaveURL(/\/planes/);

  // Lo aceptado queda a la vista en la cuenta.
  await page.goto("/cuenta");
  const aceptados = page.locator("section", { hasText: "Documentos aceptados" });
  await expect(aceptados.getByText("Términos y Condiciones")).toBeVisible();
  await expect(aceptados.getByText("Política de Tratamiento de Datos Personales")).toBeVisible();
  await expect(aceptados.getByText("Vigente", { exact: true })).toHaveCount(2);
});

test("onboarding: la primera entrada a la mesa pide leer hasta el final", async ({
  page,
  request,
}) => {
  const email = uniqueEmail();
  await registerViaApi(request, email, { onboarding: "pendiente" });
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/dashboard/);

  await page.getByRole("button", { name: /abrir mesa europea/i }).click();
  await page.getByPlaceholder("17, 32, 0, 15, 4").fill("17, 32, 0, 15, 4, 21, 2, 25, 17, 34, 6, 27");
  await page.getByLabel(/Del más antiguo al más reciente/).check();
  await page.getByRole("button", { name: "Empezar sesión" }).click();
  await expect(page).toHaveURL(/\/games\/roulette\/[0-9a-f-]+/);

  // En lugar de la mesa, la pantalla que explica qué hace y qué no hace.
  await expect(
    page.getByRole("heading", { level: 1, name: "Qué hace y qué no hace Sebasanálisis" }),
  ).toBeVisible();
  await expect(page.getByText("Recomendación para el siguiente giro", { exact: true })).toHaveCount(0);
  const continuar = page.getByRole("button", { name: "Entendido, continuar" });
  await expect(continuar).toBeDisabled();

  // El botón se habilita al llegar al final del texto.
  await page.getByTestId("onboarding-texto").evaluate((el) => el.scrollTo(0, el.scrollHeight));
  await expect(continuar).toBeEnabled();
  await continuar.click();
  await expect(page.getByText("Recomendación para el siguiente giro", { exact: true })).toBeVisible();

  // Solo se muestra una vez.
  await page.reload();
  await expect(page.getByText("Recomendación para el siguiente giro", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Qué hace y qué no hace Sebasanálisis" }),
  ).toHaveCount(0);
});

test("mi cuenta: descargar mis datos entrega el archivo", async ({ page, request }) => {
  const email = uniqueEmail();
  await registerViaApi(request, email);
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/dashboard/);

  await page.goto("/cuenta");
  const descarga = page.waitForEvent("download");
  await page.getByRole("button", { name: "Descargar mis datos" }).click();
  expect((await descarga).suggestedFilename()).toBe("sebasanalisis-mis-datos.json");
});
