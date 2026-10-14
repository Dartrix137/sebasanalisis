import { expect, test } from "@playwright/test";
import type { Browser, Page } from "@playwright/test";

import {
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  PASSWORD,
  linkFromEmail,
  loginViaUi,
  registerViaApi,
  uniqueEmail,
} from "./helpers";

/**
 * El admin por secciones (paso 6 de la Fase 4, entrega 2; §4.1, §4.2 y §4.7):
 * navegación lateral, resumen, forzar el restablecimiento de la contraseña y
 * reenviar el correo de confirmación.
 */

async function adminPanel(browser: Browser): Promise<{ panel: Page; close: () => Promise<void> }> {
  const context = await browser.newContext();
  const panel = await context.newPage();
  await loginViaUi(panel, ADMIN_EMAIL, ADMIN_PASSWORD);
  await expect(panel).toHaveURL(/\/dashboard/);
  return { panel, close: () => context.close() };
}

async function openAccount(panel: Page, email: string) {
  await panel.goto("/admin/usuarios");
  await panel.getByLabel("Buscar por correo o nombre").fill(email);
  await panel.getByRole("button", { name: "Buscar" }).click();
  const fila = panel.locator("li", { hasText: email });
  await fila.getByRole("button", { name: "Ver" }).click();
  return fila;
}

test("el administrador entra al resumen y recorre las secciones por la navegación", async ({
  browser,
}) => {
  const { panel, close } = await adminPanel(browser);
  // El administrador sembrado no ha aceptado los documentos: la mesa le pide
  // aceptarlos y esa pantalla no lleva el encabezado. El resumen no los pide.
  await panel.goto("/admin");

  await expect(panel.getByRole("heading", { level: 1, name: "Resumen" })).toBeVisible();
  await expect(panel.getByText(/frente al mismo tramo del mes anterior/)).toBeVisible();
  await expect(panel.getByText("Ingreso recurrente mensual")).toBeVisible();
  await expect(panel.getByText("Altas", { exact: true })).toBeVisible();
  await expect(panel.getByText("Cobrado, neto de reembolsos")).toBeVisible();

  const nav = panel.getByRole("navigation", { name: "Administración" });
  await expect(nav.getByRole("link", { name: "Resumen" })).toHaveAttribute("aria-current", "page");
  for (const [link, heading] of [
    ["Usuarios", "Usuarios"],
    ["Suscripciones", "Suscripciones"],
    ["Pagos", "Pagos"],
    ["Planes", "Planes"],
    ["Bitácora", "Bitácora"],
  ] as const) {
    await nav.getByRole("link", { name: link }).click();
    await expect(panel.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    await expect(nav.getByRole("link", { name: link })).toHaveAttribute("aria-current", "page");
  }
  // Juegos y Motor existen en la navegación (los dos piden los documentos
  // aceptados, como la mesa: el administrador sembrado no los ha aceptado).
  await expect(nav.getByRole("link", { name: "Juegos" })).toHaveAttribute("href", "/admin/juegos");
  await expect(nav.getByRole("link", { name: "Motor" })).toHaveAttribute("href", "/admin/motor");
  await close();
});

test("una cuenta que no es administradora no ve el admin", async ({ page, request }) => {
  const email = uniqueEmail();
  await registerViaApi(request, email);
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/dashboard/);
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByRole("navigation", { name: "Administración" })).toHaveCount(0);
});

test("forzar el restablecimiento cierra la sesión y la contraseña anterior deja de servir", async ({
  page,
  request,
  browser,
}) => {
  const email = uniqueEmail();
  const nueva = "clave-nueva-tras-el-admin-321";
  await registerViaApi(request, email);
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/dashboard/);

  const { panel, close } = await adminPanel(browser);
  const fila = await openAccount(panel, email);
  const forma = fila.getByRole("form", { name: "Forzar el restablecimiento de la contraseña" });
  await forma.getByLabel("Motivo del restablecimiento").fill(`Acceso sospechoso (${email})`);
  const boton = forma.getByRole("button", { name: "Forzar el restablecimiento" });
  await expect(boton).toBeDisabled();
  await forma.getByRole("checkbox").check();
  await boton.click();
  await expect(forma.getByText(/sus sesiones se cerraron/)).toBeVisible();
  await expect(fila.getByText("Forzó el restablecimiento de la contraseña")).toBeVisible();
  await close();

  // Su sesión quedó cerrada y la contraseña de siempre ya no entra.
  await page.reload();
  await expect(page).toHaveURL(/\/login/);
  await loginViaUi(page, email, PASSWORD);
  await expect(page.getByText("Correo o contrasena incorrectos")).toBeVisible();

  // Con el enlace del correo elige una nueva y entra.
  await page.goto(await linkFromEmail(email, "Elige una contraseña nueva"));
  await page.locator("#new-password").fill(nueva);
  await page.getByRole("button", { name: "Guardar contraseña" }).click();
  await expect(page.getByRole("status")).toContainText("Tu contraseña cambió");
  await loginViaUi(page, email, nueva);
  await expect(page).toHaveURL(/\/dashboard/);
});

test("reenviar el correo de confirmación desde el detalle de la cuenta", async ({
  request,
  browser,
}) => {
  const email = uniqueEmail();
  await registerViaApi(request, email);

  const { panel, close } = await adminPanel(browser);
  const fila = await openAccount(panel, email);
  await fila.getByRole("button", { name: "Reenviar el correo de confirmación" }).click();
  await expect(fila.getByText(`Le enviamos el correo de confirmación a ${email}`)).toBeVisible();
  await expect(fila.getByText("Reenvió el correo de confirmación")).toBeVisible();
  await close();

  // Le llegó el enlace y confirma el correo con él.
  const enlace = await linkFromEmail(email, "Confirma tu correo");
  const token = new URL(enlace).searchParams.get("token");
  const API = process.env.E2E_API_URL ?? "";
  const confirmado = await request.post(`${API}/auth/verify-email`, { data: { token } });
  expect(confirmado.ok()).toBeTruthy();
});
