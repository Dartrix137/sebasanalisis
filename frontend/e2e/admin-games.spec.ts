import { expect, test } from "@playwright/test";
import type { APIRequestContext, Browser, Page } from "@playwright/test";

import { ADMIN_EMAIL, ADMIN_PASSWORD, API_URL, loginViaUi } from "./helpers";

/**
 * Juegos y planes en el admin (paso 7 de la Fase 4, entrega 1; §7.2 y §7.4):
 * el alta de juegos oculta (por ahora solo la ruleta), cambiar el estado de un
 * juego con motivo y elegir los juegos que incluye un plan.
 *
 * Cada test crea su propio juego y su propio plan: los planes sembrados los
 * usan los demás tests en paralelo y siguen incluyendo todos los juegos.
 */

const rand = () => Math.random().toString(36).slice(2, 8);

async function adminPanel(browser: Browser): Promise<{ panel: Page; close: () => Promise<void> }> {
  const context = await browser.newContext();
  const panel = await context.newPage();
  await loginViaUi(panel, ADMIN_EMAIL, ADMIN_PASSWORD);
  await expect(panel).toHaveURL(/\/dashboard/);
  return { panel, close: () => context.close() };
}

async function adminToken(request: APIRequestContext): Promise<string> {
  const login = await request.post(`${API_URL}/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  return ((await login.json()) as { access_token: string }).access_token;
}

test("el alta de juegos está oculta; el administrador cambia el estado de un juego con motivo", async ({
  browser,
  request,
}) => {
  // Por ahora el producto es solo la ruleta (decisión del 2026-10-14): la
  // pantalla no ofrece crear juegos ni variantes. El juego de prueba se crea
  // por la API, que conserva el alta.
  const sufijo = rand();
  const slug = `dados-${sufijo}`;
  const creado = await request.post(`${API_URL}/admin/games`, {
    headers: { Authorization: `Bearer ${await adminToken(request)}` },
    data: {
      name: `Dados ${sufijo}`,
      type: `dice_${sufijo}`,
      slug,
      module: "discrete_outcome",
      icon: "dados",
      reason: "Juego para un test de punta a punta",
    },
  });
  expect(creado.ok()).toBeTruthy();

  const { panel, close } = await adminPanel(browser);
  await panel.goto("/admin/juegos");
  await expect(panel.getByRole("heading", { level: 1, name: "Juegos" })).toBeVisible();
  // La ruleta sembrada está, con su slug en español, y sus variantes se editan.
  const ruleta = panel.getByTestId("game-ruleta");
  await expect(ruleta.getByText("/juegos/ruleta")).toBeVisible();
  await expect(ruleta.getByRole("button", { name: "Editar", exact: true }).first()).toBeVisible();
  await expect(panel.getByRole("button", { name: "Crear juego" })).toHaveCount(0);
  await expect(panel.getByRole("button", { name: "+ Variante" })).toHaveCount(0);

  // Nace oculto.
  await panel.getByLabel("Buscar").fill(slug);
  const juego = panel.getByTestId(`game-${slug}`);
  await expect(juego.getByText(`/juegos/${slug}`)).toBeVisible();
  await expect(juego.getByText("Oculto", { exact: true })).toBeVisible();

  await juego.getByRole("button", { name: "Editar juego" }).click();
  await juego.getByLabel("Estado").selectOption("coming_soon");
  // Cambiar el estado pide motivo.
  await juego.getByLabel("Motivo del cambio de estado").fill("Se anuncia en el menú");
  await juego.getByRole("button", { name: "Guardar" }).click();
  await expect(juego.getByText("Próximamente", { exact: true })).toBeVisible();

  await panel.goto("/admin/auditoria");
  await expect(panel.getByText("Cambió el estado de un juego").first()).toBeVisible();
  await close();
});

test("el administrador elige los juegos de un plan y queda en la bitácora", async ({
  browser,
  request,
}) => {
  const token = await adminToken(request);
  const headers = { Authorization: `Bearer ${token}` };
  const sufijo = rand();
  const juego = await request.post(`${API_URL}/admin/games`, {
    headers,
    data: {
      name: `Cartas ${sufijo}`,
      type: `cards_${sufijo}`,
      slug: `cartas-${sufijo}`,
      module: "discrete_outcome",
      icon: "cartas",
      reason: "Juego para un test de punta a punta",
    },
  });
  expect(juego.ok()).toBeTruthy();
  const code = `e2e-${rand()}`;
  const plan = await request.post(`${API_URL}/admin/plans`, {
    headers,
    data: {
      code,
      name: `Plan juegos ${sufijo}`,
      description: "Plan de los juegos incluidos (e2e).",
      price_cents: 10_000_000,
      interval: "month",
      active: false,
      reason: "Plan para probar los juegos incluidos",
    },
  });
  expect(plan.ok()).toBeTruthy();

  const { panel, close } = await adminPanel(browser);
  await panel.goto("/admin/planes");
  const fila = panel.getByTestId(`plan-${code}`);
  await expect(fila.getByText(/todos los juegos/)).toBeVisible();
  await fila.getByRole("button", { name: "Editar" }).click();

  const juegos = fila.getByRole("region", { name: "Juegos incluidos" });
  await juegos.getByRole("checkbox", { name: /Todos los juegos/ }).uncheck();
  await juegos.getByRole("checkbox", { name: new RegExp(`Cartas ${sufijo}`) }).check();
  await juegos.getByLabel("Motivo del cambio de juegos").fill("Plan solo de cartas");
  await juegos.getByRole("button", { name: "Guardar juegos" }).click();
  await expect(fila.getByText("1 juego", { exact: false })).toBeVisible();

  await panel.goto("/admin/auditoria");
  await expect(panel.getByText("Cambió los juegos del plan").first()).toBeVisible();
  await close();
});
