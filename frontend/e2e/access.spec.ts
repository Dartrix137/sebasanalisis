import { expect, test } from "@playwright/test";

import {
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  loginViaUi,
  registerViaApi,
  uniqueEmail,
} from "./helpers";

/**
 * Control de acceso del paso 3 de la Fase 4 (§2, §13.3): una cuenta sin acceso
 * no ve la mesa, y la ve cuando un administrador se lo otorga.
 */

const MESA = { name: "Abrir una mesa nueva" };

test("cuenta sin acceso: no ve la mesa hasta que el administrador le da acceso", async ({
  page,
  request,
  browser,
}) => {
  const email = uniqueEmail();
  await registerViaApi(request, email, { access: "ninguno" });
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/dashboard/);

  // En lugar del menú de mesas, el aviso. Sin precios ni nada que comprar.
  await expect(
    page.getByRole("heading", { level: 1, name: "Tu cuenta no tiene acceso activo" }),
  ).toBeVisible();
  await expect(page.getByText("Las suscripciones estarán disponibles pronto.")).toBeVisible();
  await expect(page.getByRole("heading", MESA)).toHaveCount(0);

  // La cuenta no queda bloqueada: "Mi cuenta" abre.
  await page.getByRole("link", { name: "Mi cuenta" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mi cuenta" })).toBeVisible();

  // El administrador la busca en /admin/usuarios y le da acceso, con motivo.
  const admin = await browser.newContext();
  const panel = await admin.newPage();
  await loginViaUi(panel, ADMIN_EMAIL, ADMIN_PASSWORD);
  await expect(panel).toHaveURL(/\/dashboard/);
  await panel.goto("/admin/usuarios");
  await panel.getByLabel("Buscar por correo o nombre").fill(email);
  await panel.getByRole("button", { name: "Buscar" }).click();

  const fila = panel.locator("li", { hasText: email });
  await expect(fila.getByText("Sin acceso", { exact: true })).toBeVisible();
  await fila.getByRole("button", { name: "Ver" }).click();
  await fila.getByLabel("Tipo de acceso").selectOption("invited");

  // Sin motivo no se guarda.
  await fila.getByRole("button", { name: "Guardar acceso" }).click();
  await expect(fila.getByText("Acceso actualizado")).toHaveCount(0);

  await fila.getByLabel("Motivo del cambio de acceso").fill("Cortesía de prueba");
  await fila.getByRole("button", { name: "Guardar acceso" }).click();
  await expect(fila.getByText("Acceso actualizado")).toBeVisible();
  await expect(fila.getByText("Invitado", { exact: true }).first()).toBeVisible();

  // Quedó en la bitácora, con quién, qué y por qué.
  await panel.goto("/admin/auditoria");
  const entrada = panel.locator("li", { hasText: "Cortesía de prueba" });
  await expect(entrada.getByText("Cambió el acceso")).toBeVisible();
  await expect(entrada.getByText(ADMIN_EMAIL)).toBeVisible();
  await expect(entrada.getByText(/access_type: invited/)).toBeVisible();
  await admin.close();

  // La cuenta vuelve al menú: ahora sí ve la mesa.
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", MESA)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Tu cuenta no tiene acceso activo" })).toHaveCount(0);
});

test("cuenta suspendida: ve el aviso y no la mesa", async ({ page, request, browser }) => {
  const email = uniqueEmail();
  await registerViaApi(request, email);
  await loginViaUi(page, email);
  await expect(page.getByRole("heading", MESA)).toBeVisible();

  const admin = await browser.newContext();
  const panel = await admin.newPage();
  await loginViaUi(panel, ADMIN_EMAIL, ADMIN_PASSWORD);
  await expect(panel).toHaveURL(/\/dashboard/);
  await panel.goto("/admin/usuarios");
  await panel.getByLabel("Buscar por correo o nombre").fill(email);
  await panel.getByRole("button", { name: "Buscar" }).click();
  const fila = panel.locator("li", { hasText: email });
  await fila.getByRole("button", { name: "Ver" }).click();
  await fila.getByLabel("Motivo de la suspensión").fill("Suspensión de prueba");
  await fila.getByRole("button", { name: "Suspender cuenta" }).click();
  await expect(fila.getByText("Suspendida", { exact: true }).first()).toBeVisible();
  await expect(fila.getByRole("button", { name: "Reactivar cuenta" })).toBeVisible();
  await admin.close();

  await page.reload();
  await expect(
    page.getByRole("heading", { level: 1, name: "Tu cuenta está suspendida" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", MESA)).toHaveCount(0);
});
