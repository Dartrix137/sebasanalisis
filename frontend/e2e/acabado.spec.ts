import { expect, test } from "@playwright/test";

import { API_URL, ADMIN_EMAIL, ADMIN_PASSWORD, loginViaUi, registerViaApi, uniqueEmail } from "./helpers";

/**
 * Acabado del frontend antes del lanzamiento (paso 9 de la Fase 4): la 404, los
 * metadatos, robots.txt y sitemap.xml, la silueta de carga, el celular y los
 * errores de formulario.
 */

test("una ruta que no existe muestra la 404 de la aplicación", async ({ page }) => {
  const response = await page.goto("/ruta-que-no-existe");
  expect(response?.status()).toBe(404);
  await expect(page.getByRole("heading", { name: "No encontramos esta página" })).toBeVisible();
  await expect(page).toHaveTitle("Página no encontrada · Sebasanálisis");
  await page.getByRole("link", { name: "Ir al inicio", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test("un documento legal que no existe también responde con la 404", async ({ page }) => {
  const response = await page.goto("/legal/no-existe");
  expect(response?.status()).toBe(404);
  await expect(page.getByRole("heading", { name: "No encontramos esta página" })).toBeVisible();
});

test("robots.txt bloquea lo privado y apunta al sitemap público", async ({ request }) => {
  const robots = await (await request.get("/robots.txt")).text();
  for (const path of ["/admin", "/cuenta", "/dashboard", "/juegos", "/pago/", "/planes/pagar"]) {
    expect(robots).toContain(`Disallow: ${path}`);
  }
  expect(robots).toContain("Sitemap: https://sebasanalisis.com/sitemap.xml");

  const sitemap = await (await request.get("/sitemap.xml")).text();
  for (const path of ["/login", "/register", "/planes", "/legal/terminos", "/legal/privacidad"]) {
    expect(sitemap).toContain(`<loc>https://sebasanalisis.com${path}</loc>`);
  }
  expect(sitemap).not.toContain("/dashboard");
  expect(sitemap).not.toContain("localhost");
});

test("cada página tiene su título, y las privadas no se indexan", async ({ page, request }) => {
  await page.goto("/login");
  await expect(page).toHaveTitle("Iniciar sesión · Sebasanálisis");
  await page.goto("/legal/terminos");
  await expect(page).toHaveTitle("Términos y Condiciones · Sebasanálisis");
  await page.goto("/planes");
  await expect(page).toHaveTitle("Planes · Sebasanálisis");
  const planes = await (await request.get("/planes")).text();
  expect(planes).not.toContain('name="robots"');

  // Los metadatos van en el HTML del servidor, con o sin sesión.
  for (const [path, title] of [
    ["/cuenta", "Mi cuenta · Sebasanálisis"],
    ["/admin/usuarios", "Usuarios · Admin · Sebasanálisis"],
    ["/admin", "Resumen · Admin · Sebasanálisis"],
    ["/juegos/ruleta", "Ruleta · Sebasanálisis"],
    ["/planes/pagar", "Confirma tu pago · Sebasanálisis"],
  ] as const) {
    const html = await (await request.get(path)).text();
    expect(html, path).toContain(`<title>${title}</title>`);
    expect(html, path).toContain('<meta name="robots" content="noindex, nofollow"/>');
  }
});

test("mientras llegan los datos se ve la silueta, no una pantalla en blanco", async ({
  page,
  request,
}) => {
  const email = uniqueEmail();
  await registerViaApi(request, email);
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/dashboard/);

  // La API tarda: la cuenta todavía no llega.
  let release: () => void = () => {};
  const blocked = new Promise<void>((resolve) => (release = resolve));
  await page.route(`${API_URL}/**`, async (route) => {
    await blocked;
    await route.continue();
  });
  await page.goto("/cuenta");
  await expect(page.getByRole("status", { name: "Cargando" })).toBeVisible();
  release();
  await expect(page.getByRole("heading", { name: "Mi cuenta" })).toBeVisible();
  await expect(page.getByRole("status", { name: "Cargando" })).toHaveCount(0);
});

test.describe("en un celular de 360 px", () => {
  test.use({ viewport: { width: 360, height: 780 } });

  test("la mesa no se sale de la pantalla con la tabla de progresión abierta", async ({
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
    // El nombre de la variante, en español.
    await expect(page.getByText("Europea", { exact: true })).toBeVisible();
    await page.getByText("Gestión de banca y tabla de progresión").click();
    await page.getByText("Ver la tabla de progresión con montos reales").click();
    await expect(page.getByRole("columnheader", { name: "Escalón" })).toBeVisible();

    const ancho = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(ancho).toBeLessThanOrEqual(360);
  });

  test("en el admin, la sección abierta queda a la vista en la fila del menú", async ({ page }) => {
    await loginViaUi(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await page.waitForURL(/\/(dashboard|admin)/);
    await page.goto("/admin/auditoria");
    const nav = page.getByRole("navigation", { name: "Administración" });
    await expect(nav.getByRole("link", { name: "Bitácora" })).toBeInViewport();
  });

  test("la mesa nueva dice el error junto al campo", async ({ page, request }) => {
    const email = uniqueEmail();
    await registerViaApi(request, email);
    await loginViaUi(page, email);
    await expect(page).toHaveURL(/\/dashboard/);
    await page.goto("/juegos/ruleta");
    await page.getByRole("button", { name: /abrir mesa europea/i }).click();

    // La etiqueta nombra al campo, no al botón de ayuda que tiene al lado.
    await page.getByRole("spinbutton", { name: "Banca inicial" }).fill("1000");
    const apuesta = page.getByRole("spinbutton", { name: "Apuesta base" });
    await apuesta.fill("5000");
    await expect(apuesta).toHaveAttribute("aria-invalid", "true");
    await expect(apuesta).toHaveAccessibleDescription("No puede superar la banca inicial.");
    await expect(page.getByText("Revisa lo marcado en rojo más arriba para poder empezar.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Empezar sesión" })).toBeDisabled();
  });
});

test("un correo que el navegador acepta y la API no, se explica en español", async ({ page }) => {
  await page.goto("/olvide-contrasena");
  await page.getByLabel("Correo electrónico").fill("a@b");
  await page.locator("form button[type=submit]").click();
  await expect(page.getByRole("alert").filter({ hasText: "correo" })).toHaveText(
    "El correo no es válido.",
  );
});
