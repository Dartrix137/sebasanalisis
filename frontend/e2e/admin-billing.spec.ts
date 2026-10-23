import { expect, test } from "@playwright/test";
import type { Browser, Page } from "@playwright/test";

import {
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  confirmEmail,
  expectEmail,
  loginViaUi,
  registerViaApi,
  uniqueEmail,
} from "./helpers";

/**
 * Suscripciones y pagos en el admin (paso 6 de la Fase 4, entrega 1; §4.3):
 * encontrar una suscripción, extenderla o cancelarla con motivo, verlo en la
 * bitácora, y registrar un reembolso en Pagos.
 *
 * La API corre con la pasarela simulada: no se cobra nada ni se sale a la red.
 */

const MESA = { name: "Elige un juego" };

/** Una cuenta nueva que paga un mes a mano en la pasarela simulada. */
async function subscriber(page: Page, request: Parameters<typeof registerViaApi>[0]) {
  const email = uniqueEmail();
  await registerViaApi(request, email, { access: "ninguno" });
  await confirmEmail(request, email);
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/planes/);
  await page
    .getByRole("article", { name: "Acceso Mensual" })
    .getByRole("link", { name: "Suscribirme" })
    .click();
  await page.getByRole("radio", { name: "Pago manual" }).check();
  await page.getByRole("button", { name: "Ir a pagar 100.000 COP" }).click();
  await page.getByRole("button", { name: "Aprobar el pago" }).click();
  await expect(page.getByText("Pago aprobado")).toBeVisible();
  return email;
}

async function adminPanel(browser: Browser): Promise<{ panel: Page; close: () => Promise<void> }> {
  const context = await browser.newContext();
  const panel = await context.newPage();
  await loginViaUi(panel, ADMIN_EMAIL, ADMIN_PASSWORD);
  await expect(panel).toHaveURL(/\/dashboard/);
  return { panel, close: () => context.close() };
}

test("el administrador encuentra una suscripción, la extiende con motivo y lo ve en la bitácora", async ({
  page,
  request,
  browser,
}) => {
  const email = await subscriber(page, request);
  const motivo = `Compensación por una caída del servicio (${email})`;

  const { panel, close } = await adminPanel(browser);
  await panel.goto("/admin/suscripciones");
  await expect(panel.getByRole("heading", { level: 1, name: "Suscripciones" })).toBeVisible();

  // La encuentra por el correo, filtrando en el servidor.
  await panel.getByLabel("Buscar por correo").fill(email);
  await panel.getByLabel("Estado").selectOption("active");
  await panel.getByRole("button", { name: "Buscar" }).click();
  const fila = panel.locator("li", { hasText: email });
  await expect(fila.getByText("Activa", { exact: true })).toBeVisible();
  await expect(panel.locator("main li").filter({ has: panel.getByRole("button", { name: "Ver" }) })).toHaveCount(1);
  await fila.getByRole("button", { name: "Ver" }).click();

  // Sin motivo no se extiende.
  const extender = fila.getByRole("form", { name: "Extender el período" });
  await extender.getByLabel("Días").fill("10");
  await extender.getByRole("button", { name: "Extender" }).click();
  await expect(extender.getByText("Listo. El cambio quedó en la bitácora.")).toHaveCount(0);

  await extender.getByLabel("Motivo").fill(motivo);
  await extender.getByRole("button", { name: "Extender" }).click();
  await expect(extender.getByText("Listo. El cambio quedó en la bitácora.")).toBeVisible();
  await expect(fila.getByText("Extendió la suscripción")).toBeVisible();
  await expect(fila.getByText(`Motivo: ${motivo}`)).toBeVisible();

  // El cliente recibe el aviso.
  await expectEmail(email, "Extendimos tu suscripción");

  // Y quedó en la bitácora general, con quién, qué y por qué.
  await panel.goto("/admin/auditoria");
  const entrada = panel.locator("li", { hasText: motivo });
  await expect(entrada.getByText("Extendió la suscripción")).toBeVisible();
  await expect(entrada.getByText(ADMIN_EMAIL)).toBeVisible();
  await expect(entrada.getByText(/days: 10/)).toBeVisible();
  await close();

  // El cliente sigue entrando a la mesa.
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", MESA)).toBeVisible();
});

test("desde el detalle de la cuenta: cancelar de inmediato quita el acceso; en Pagos, registrar un reembolso", async ({
  page,
  request,
  browser,
}) => {
  const email = await subscriber(page, request);
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", MESA)).toBeVisible();

  const { panel, close } = await adminPanel(browser);
  await panel.goto("/admin/usuarios");
  await panel.getByLabel("Buscar por correo o nombre").fill(email);
  await panel.getByRole("button", { name: "Buscar" }).click();
  const cuenta = panel.locator("li", { hasText: email });
  await cuenta.getByRole("button", { name: "Ver" }).click();

  // La ficha del usuario resume la suscripción; las acciones están en
  // Suscripciones, que abre con el detalle de esa cuenta ya desplegado.
  await expect(cuenta.getByRole("form", { name: "Cancelar de inmediato" })).toHaveCount(0);
  await cuenta.getByRole("link", { name: "Extender o cancelar en Suscripciones →" }).click();
  await expect(panel).toHaveURL(/\/admin\/suscripciones\?query=/);
  const fila = panel.locator("li", { hasText: email });

  // Cancelar de inmediato pide confirmarlo además del motivo.
  const cancelar = fila.getByRole("form", { name: "Cancelar de inmediato" });
  await cancelar.getByLabel("Motivo").fill(`Uso indebido de la cuenta (${email})`);
  const boton = cancelar.getByRole("button", { name: "Cancelar de inmediato" });
  await expect(boton).toBeDisabled();
  await cancelar.getByRole("checkbox").check();
  await boton.click();
  await expect(fila.getByText("Canceló la suscripción de inmediato")).toBeVisible();
  await expect(fila.getByText("Sin período vigente.")).toBeVisible();
  await expectEmail(email, "Tu suscripción a Sebasanálisis terminó");

  // El pago sigue aprobado: el reembolso se hace en la pasarela y aquí se registra.
  await fila.getByRole("link", { name: /^SA-/ }).click();
  await expect(panel).toHaveURL(/\/admin\/pagos\?query=SA-/);
  const pago = panel.locator("li", { hasText: email });
  await expect(pago.getByText("Aprobado", { exact: true })).toBeVisible();
  await pago.getByRole("button", { name: "Ver" }).click();
  const detalle = panel.getByTestId("detalle-pago");
  // El pago aprobado dejó su factura, pendiente: la emisión es del paso 5.4.
  await expect(
    detalle.getByText("Pendiente de emitir: la emisión todavía no está encendida"),
  ).toBeVisible();
  await expect(detalle.getByText("Día de la operación")).toBeVisible();
  await detalle.getByLabel("Monto (COP)").fill("50000");
  await detalle.getByLabel("Fecha en la pasarela").fill(new Date().toISOString().slice(0, 10));
  await detalle.getByLabel("Motivo del reembolso").fill(`Devolución parcial (${email})`);
  await detalle.getByRole("button", { name: "Registrar reembolso" }).click();
  // Queda en la lista de reembolsos y en lo reembolsado del pago.
  await expect(detalle.getByText("50.000 COP", { exact: true })).toHaveCount(2);
  await expect(detalle.getByText("Reembolsado", { exact: true })).toBeVisible();
  await expect(detalle.getByText("Registró un reembolso")).toBeVisible();
  await close();

  // La cuenta ya no entra a la mesa: va a los planes.
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/planes/);
  await expect(page.getByRole("heading", MESA)).toHaveCount(0);
});
