import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import {
  API_URL,
  adminAuth,
  confirmEmail,
  loginViaUi,
  registerViaApi,
  uniqueEmail,
} from "./helpers";

/**
 * Plataforma multijuego (paso 7 de la Fase 4, entrega 2; §7.6): la mesa en
 * `/juegos/<slug>/mesa/<id>`, la redirección de la ruta vieja, el menú de
 * juegos y el fixture de dados de punta a punta.
 *
 * El dado es solo un fixture de test (§7.5): cada test que lo necesita lo crea
 * por la API de admin con un slug propio, en la base desechable de e2e. No se
 * siembra ni se publica.
 */

const DADOS = JSON.parse(
  readFileSync(path.resolve(__dirname, "..", "..", "backend", "tests", "fixtures", "dados_d6.json"), "utf-8"),
) as Record<string, unknown>;

const LINEA_FIJA =
  "Recomendación generada a partir del análisis estadístico de los resultados registrados. No es una predicción.";

const rand = () => Math.random().toString(36).slice(2, 8);

/** Crea un juego con una variante del dado, como lo hace un administrador. */
async function createDiceGame(
  request: APIRequestContext,
  status: "active" | "coming_soon" = "active",
): Promise<{ id: string; name: string; slug: string }> {
  const headers = await adminAuth(request);
  const sufijo = rand();
  const created = await request.post(`${API_URL}/admin/games`, {
    headers,
    data: {
      name: `Dados ${sufijo}`,
      type: `dice_${sufijo}`,
      slug: `dados-${sufijo}`,
      module: "discrete_outcome",
      icon: "dados",
      description: "Un dado de seis caras (fixture de test).",
      status,
      reason: "Fixture de dados para un test de punta a punta",
    },
  });
  expect(created.ok()).toBeTruthy();
  const game = (await created.json()) as { id: string; name: string; slug: string };
  const variant = await request.post(`${API_URL}/admin/games/${game.id}/variants`, {
    headers,
    data: { name: "d6", description: "Un dado de seis caras.", house_edge: 0.05, config: DADOS },
  });
  expect(variant.ok()).toBeTruthy();
  return game;
}

test("la ruta vieja de la mesa redirige a la nueva", async ({ page, request }) => {
  const email = uniqueEmail();
  const token = await registerViaApi(request, email);
  const headers = { Authorization: `Bearer ${token}` };

  const menu = (await (await request.get(`${API_URL}/games`, { headers })).json()) as {
    items: { slug: string; variants: { id: string; name: string }[] }[];
  };
  const ruleta = menu.items.find((g) => g.slug === "ruleta");
  const europea = ruleta?.variants.find((v) => v.name === "european");
  expect(europea).toBeTruthy();
  const created = await request.post(`${API_URL}/sessions`, {
    headers,
    data: {
      game_variant_id: europea!.id,
      bankroll_start: 100_000,
      base_bet: 1_000,
      table_limit: 500_000,
    },
  });
  expect(created.ok()).toBeTruthy();
  const { id } = (await created.json()) as { id: string };

  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/dashboard/);
  await page.goto(`/games/roulette/${id}`);
  await expect(page).toHaveURL(new RegExp(`/juegos/ruleta/mesa/${id}$`));
  await expect(page.getByText("Recomendación para el siguiente giro")).toBeVisible();

  // Un slug equivocado lleva al del juego de la mesa.
  await page.goto(`/juegos/otro-juego/mesa/${id}`);
  await expect(page).toHaveURL(new RegExp(`/juegos/ruleta/mesa/${id}$`));
});

test("un juego de dados creado desde el admin aparece en el menú y se juega", async ({
  page,
  request,
}) => {
  const dados = await createDiceGame(request);
  const email = uniqueEmail();
  await registerViaApi(request, email);
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/dashboard/);

  // En el menú, con su descripción, y lleva a la página del juego.
  const tarjeta = page.getByTestId(`juego-${dados.slug}`);
  await expect(tarjeta.getByText("Un dado de seis caras (fixture de test).")).toBeVisible();
  await page.getByRole("link", { name: `Jugar ${dados.name}` }).click();
  await expect(page).toHaveURL(new RegExp(`/juegos/${dados.slug}$`));

  await page.getByRole("button", { name: "Abrir mesa d6" }).click();
  await page
    .getByRole("textbox", { name: /Números ya observados en la mesa/ })
    .fill("2, 4, 6, 2, 4, 6, 2, 4, 6, 2, 4, 6");
  await page.getByLabel(/Del más antiguo al más reciente/).check();
  await page.getByRole("button", { name: "Empezar sesión" }).click();
  await expect(page).toHaveURL(new RegExp(`/juegos/${dados.slug}/mesa/[0-9a-f-]+$`));

  // El teclado sale de `possible_outcomes`: seis caras, en seis columnas.
  const teclado = page.getByTestId("teclado");
  await expect(teclado.getByRole("button")).toHaveCount(6);
  await expect(teclado).toHaveAttribute("style", /repeat\(6, minmax\(0px, 1fr\)\)|repeat\(6, minmax\(0, 1fr\)\)/);

  // La tarjeta de recomendación, con su línea fija obligatoria.
  await expect(page.getByText("Recomendación para el siguiente giro")).toBeVisible();
  await expect(page.getByText(LINEA_FIJA)).toBeVisible();

  await teclado.getByRole("button", { name: "4", exact: true }).click();
  await expect(page.getByText(/Salió el 4\b/)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: /^(APOSTAR: |NO APOSTAR ESTE GIRO)/ }),
  ).toBeVisible();
  await expect(page.getByText(LINEA_FIJA)).toBeVisible();
});

test("un juego próximamente se ve en el menú pero no abre mesa", async ({ page, request }) => {
  const pronto = await createDiceGame(request, "coming_soon");
  const email = uniqueEmail();
  await registerViaApi(request, email);
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/dashboard/);

  const tarjeta = page.getByTestId(`juego-${pronto.slug}`);
  await expect(tarjeta.getByText("Próximamente")).toBeVisible();
  await expect(tarjeta.getByRole("link")).toHaveCount(0);

  await page.goto(`/juegos/${pronto.slug}`);
  await expect(page.getByRole("heading", { name: `${pronto.name}: próximamente` })).toBeVisible();
  await expect(page.getByRole("button", { name: /Abrir mesa/ })).toHaveCount(0);
});

test("un juego fuera del plan: disponible en otro plan, sin mesa", async ({ page, request }) => {
  const dados = await createDiceGame(request);
  const headers = await adminAuth(request);
  const name = `Plan dados ${rand()}`;
  const plan = await request.post(`${API_URL}/admin/plans`, {
    headers,
    data: {
      code: `e2e-${rand()}`,
      name,
      description: "Plan que solo incluye el dado (e2e).",
      price_cents: 10_000_000,
      interval: "month",
      reason: "Plan para probar el acceso por juego",
    },
  });
  expect(plan.ok()).toBeTruthy();
  const { id: planId } = (await plan.json()) as { id: string };
  const juegos = await request.put(`${API_URL}/admin/plans/${planId}/games`, {
    headers,
    data: { game_ids: [dados.id], reason: "El plan solo incluye el dado" },
  });
  expect(juegos.ok()).toBeTruthy();

  // Una cuenta se suscribe a ese plan. En /planes dice qué juego incluye.
  const email = uniqueEmail();
  await registerViaApi(request, email, { access: "ninguno" });
  await confirmEmail(request, email);
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/planes/);
  const tarjetaPlan = page.getByRole("article", { name });
  await expect(tarjetaPlan.getByText(`Incluye: ${dados.name}`)).toBeVisible();
  await tarjetaPlan.getByRole("link", { name: "Suscribirme" }).click();
  await page.getByRole("radio", { name: "Pago manual" }).check();
  await page.getByRole("button", { name: "Ir a pagar 100.000 COP" }).click();
  await page.getByRole("button", { name: "Aprobar el pago" }).click();
  await expect(page.getByText("Pago aprobado")).toBeVisible();

  // En el menú, la ruleta queda disponible en otro plan; el dado se juega.
  await page.goto("/dashboard");
  const ruleta = page.getByTestId("juego-ruleta");
  await expect(ruleta.getByText("Disponible en otro plan.")).toBeVisible();
  await expect(ruleta.getByRole("link", { name: "Ver planes" })).toHaveAttribute("href", "/planes");
  await expect(page.getByRole("link", { name: "Jugar Ruleta" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: `Jugar ${dados.name}` })).toBeVisible();

  // Y su página no ofrece abrir mesa.
  await page.goto("/juegos/ruleta");
  await expect(
    page.getByRole("heading", { name: "Este juego no está incluido en tu plan" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /Abrir mesa/ })).toHaveCount(0);
});
