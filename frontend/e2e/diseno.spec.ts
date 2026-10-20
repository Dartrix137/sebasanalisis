import { expect, test } from "@playwright/test";

import {
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  API_URL,
  loginViaUi,
  registerViaApi,
  uniqueEmail,
} from "./helpers";

/**
 * Revisión de diseño del paso 9 (2026-10-20), móvil primero: la mesa con el
 * teclado bajo la recomendación, objetivos táctiles de 44 px, un solo
 * encabezado con el menú de la cuenta y el admin con selector de sección.
 */

const CELULAR = { width: 360, height: 780 };

test.describe("en el celular", () => {
  test.use({ viewport: CELULAR });

  test("la mesa: teclado de seis columnas, teclas de 44 px y el 0 a lo ancho", async ({
    page,
    request,
  }) => {
    const email = uniqueEmail();
    const token = await registerViaApi(request, email);
    const headers = { Authorization: `Bearer ${token}` };
    const menu = (await (await request.get(`${API_URL}/games`, { headers })).json()) as {
      items: { slug: string; variants: { id: string; name: string }[] }[];
    };
    const europea = menu.items
      .find((g) => g.slug === "ruleta")!
      .variants.find((v) => v.name === "european")!;
    const created = await request.post(`${API_URL}/sessions`, {
      headers,
      data: { game_variant_id: europea.id, bankroll_start: 100_000, base_bet: 1_000, table_limit: 500_000 },
    });
    const { id } = (await created.json()) as { id: string };

    await loginViaUi(page, email);
    await expect(page).toHaveURL(/\/dashboard/);
    await page.goto(`/juegos/ruleta/mesa/${id}`);

    const teclado = page.getByTestId("teclado");
    await expect(teclado).toHaveAttribute("style", /repeat\(6, minmax\(0(px)?, 1fr\)\)/);
    await expect(teclado.getByRole("button")).toHaveCount(37);

    for (const n of ["0", "1", "36"]) {
      const caja = await teclado.getByRole("button", { name: n, exact: true }).boundingBox();
      expect(caja!.width, `ancho de la tecla ${n}`).toBeGreaterThanOrEqual(44);
      expect(caja!.height, `alto de la tecla ${n}`).toBeGreaterThanOrEqual(44);
    }
    // El 0 ocupa la fila entera: el resto queda en seis filas completas.
    const cero = await teclado.getByRole("button", { name: "0", exact: true }).boundingBox();
    const fila = await teclado.boundingBox();
    expect(cero!.width).toBeGreaterThan(fila!.width - 2);

    // Volver al menú sigue a un toque, en la franja de la mesa.
    await expect(page.getByRole("link", { name: "Volver al menú" })).toBeVisible();
    const ancho = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(ancho).toBeLessThanOrEqual(CELULAR.width);
  });

  test("el admin elige la sección con un selector", async ({ page }) => {
    await loginViaUi(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await page.waitForURL(/\/(dashboard|admin)/);
    await page.goto("/admin");
    const seccion = page.getByRole("combobox", { name: "Administración" });
    await expect(seccion).toHaveValue("/admin");
    await seccion.selectOption({ label: "Bitácora" });
    await expect(page).toHaveURL(/\/admin\/auditoria$/);
    await expect(page.getByRole("heading", { level: 1, name: "Bitácora" })).toBeVisible();
  });

  test("los filtros de usuarios van plegados y dicen cuántos hay puestos", async ({ page }) => {
    await loginViaUi(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await page.waitForURL(/\/(dashboard|admin)/);
    await page.goto("/admin/usuarios");
    const rol = page.getByRole("combobox", { name: "Rol" });
    await expect(rol).toBeHidden();
    await page.getByRole("button", { name: "Filtros" }).click();
    await rol.selectOption({ label: "Administrador" });
    await page.getByRole("button", { name: "Ocultar filtros" }).click();
    await expect(page.getByRole("button", { name: "Filtros (1)" })).toBeVisible();
  });
});

test("el menú de la cuenta: se abre, lleva a la cuenta y se cierra con Escape", async ({
  page,
  request,
}) => {
  const email = uniqueEmail();
  await registerViaApi(request, email);
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/dashboard/);

  const boton = page.getByRole("button", { name: "Menú de la cuenta" });
  await expect(boton).toHaveAttribute("aria-expanded", "false");
  await boton.click();
  await expect(boton).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("banner").getByText(email)).toBeVisible();
  // Una cuenta normal no ve la administración.
  await expect(page.getByRole("link", { name: "Administración" })).toHaveCount(0);

  await page.keyboard.press("Escape");
  await expect(boton).toHaveAttribute("aria-expanded", "false");
  await expect(boton).toBeFocused();

  await boton.click();
  await page.getByRole("link", { name: "Mi cuenta", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mi cuenta" })).toBeVisible();

  await page.getByRole("button", { name: "Menú de la cuenta" }).click();
  await page.getByRole("button", { name: "Salir" }).click();
  await expect(page).toHaveURL(/\/login/);
});

test("sin sesión, el encabezado ofrece entrar y crear cuenta", async ({ page }) => {
  await page.goto("/planes");
  const banner = page.getByRole("banner");
  await expect(banner.getByRole("link", { name: "Entrar" })).toBeVisible();
  await expect(banner.getByRole("link", { name: "Crear cuenta" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Menú de la cuenta" })).toHaveCount(0);
});
