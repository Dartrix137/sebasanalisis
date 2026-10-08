import { expect, test } from "@playwright/test";

import {
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  loginViaUi,
  registerViaApi,
  uniqueEmail,
} from "./helpers";

/**
 * Versión nueva de los términos → la mesa pide re-aceptar → se acepta y se
 * entra (§13.3, paso 2).
 *
 * Corre en el proyecto `serial` (playwright.config.ts): publicar una versión
 * le pide re-aceptar a todas las cuentas de la base, y en paralelo le cortaría
 * la mesa a los demás tests.
 */

const TITULO = "Términos y Condiciones";

test("versión nueva de los términos: la mesa pide re-aceptar y después deja entrar", async ({
  page,
  request,
  browser,
}) => {
  const marca = `Cláusula de prueba ${Date.now()}`;

  // Una cuenta al día, con su mesa a la vista.
  const email = uniqueEmail();
  await registerViaApi(request, email);
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByRole("heading", { name: "Abrir una mesa nueva" })).toBeVisible();

  // En otra sesión, el administrador publica una versión nueva desde /admin/legal.
  const admin = await browser.newContext();
  const panel = await admin.newPage();
  await loginViaUi(panel, ADMIN_EMAIL, ADMIN_PASSWORD);
  // El administrador sembrado es una cuenta anterior al paso 2: no tiene
  // consentimientos. El panel legal le abre igual.
  await expect(panel).toHaveURL(/\/dashboard/);
  await panel.goto("/admin/legal");

  const tarjeta = panel.locator("section", {
    has: panel.getByRole("heading", { name: TITULO }),
  });
  await tarjeta.getByRole("button", { name: "Preparar versión nueva" }).click();
  await tarjeta
    .getByLabel("Texto (Markdown)")
    .fill(`## ${marca}\n\nTexto nuevo.\n\n<b id="html-crudo">no debe ser un elemento</b>`);
  await tarjeta.getByRole("checkbox", { name: /Exigir que todas las cuentas acepten/ }).check();

  // La vista previa usa el mismo renderizador que la página pública.
  await tarjeta.getByRole("button", { name: "Vista previa" }).click();
  await expect(tarjeta.getByRole("heading", { name: marca })).toBeVisible();
  await tarjeta.getByRole("button", { name: "Seguir editando" }).click();

  await tarjeta.getByRole("button", { name: /^Publicar versión \d+$/ }).click();
  await tarjeta.getByRole("button", { name: /^Sí, publicar la versión \d+$/ }).click();
  await expect(tarjeta.getByText(/Vigente: versión \d+, publicada el/)).toBeVisible();
  await expect(tarjeta.getByRole("button", { name: "Preparar versión nueva" })).toBeVisible();

  // Publicada, no se edita: el panel ya no ofrece el texto de esa versión.
  await expect(tarjeta.getByLabel("Texto (Markdown)")).toHaveCount(0);

  // La página pública muestra la versión nueva, y el HTML escrito en el texto
  // sale como texto, no como elemento.
  await panel.goto("/legal/terminos");
  await expect(panel.getByRole("heading", { name: marca })).toBeVisible();
  await expect(panel.locator("#html-crudo")).toHaveCount(0);
  await expect(panel.locator("article b")).toHaveCount(0);
  await admin.close();

  // La cuenta que estaba al día vuelve a la mesa: se le pide aceptar.
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Antes de continuar" })).toBeVisible();
  await expect(page.getByRole("heading", { name: marca })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Abrir una mesa nueva" })).toHaveCount(0);

  // La cuenta no queda bloqueada: "Mi cuenta" sigue abriendo.
  await page.getByRole("link", { name: "Mi cuenta" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mi cuenta" })).toBeVisible();
  await expect(page.getByText("Versión anterior")).toBeVisible();

  // Sin marcar la casilla no se puede continuar; marcándola, se entra.
  await page.goto("/dashboard");
  const aceptar = page.getByRole("button", { name: "Aceptar y continuar" });
  await expect(aceptar).toBeDisabled();
  await page.getByRole("checkbox", { name: /He leído y acepto/ }).check();
  await aceptar.click();
  await expect(page.getByRole("heading", { name: "Abrir una mesa nueva" })).toBeVisible();

  // Y no se vuelve a pedir.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Abrir una mesa nueva" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Antes de continuar" })).toHaveCount(0);
});
