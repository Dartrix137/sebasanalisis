import { expect, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import {
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  API_URL,
  confirmEmail,
  loginViaUi,
  registerViaApi,
  uniqueEmail,
} from "./helpers";

/**
 * Trasladar el precio de un plan a sus suscripciones vigentes (paso 6 de la
 * Fase 4, entrega 3; §4.10). Los avisos los envía el job de renovaciones, que
 * aquí no corre: este recorrido es el del administrador.
 *
 * Cada test crea su propio plan: el plan mensual lo usan los demás tests en
 * paralelo y su precio no se toca.
 */

async function createPlan(request: APIRequestContext, name: string): Promise<string> {
  const login = await request.post(`${API_URL}/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  const { access_token } = (await login.json()) as { access_token: string };
  const created = await request.post(`${API_URL}/admin/plans`, {
    headers: { Authorization: `Bearer ${access_token}` },
    data: {
      code: `e2e-${Math.random().toString(36).slice(2, 10)}`,
      name,
      description: "Plan del traslado de precio (e2e).",
      price_cents: 10_000_000,
      interval: "month",
      reason: "Plan para probar el traslado de precio",
    },
  });
  expect(created.ok()).toBeTruthy();
  return ((await created.json()) as { code: string }).code;
}

test("el administrador traslada el precio nuevo de un plan a sus suscripciones y lo cancela", async ({
  page,
  request,
  browser,
}) => {
  const name = `Plan traslado ${Math.random().toString(36).slice(2, 7)}`;
  const code = await createPlan(request, name);

  // Una cuenta se suscribe a ese plan a 100.000 COP.
  const email = uniqueEmail();
  await registerViaApi(request, email, { access: "ninguno" });
  await confirmEmail(request, email);
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/planes/);
  await page.getByRole("article", { name }).getByRole("link", { name: "Suscribirme" }).click();
  await page.getByRole("radio", { name: "Pago manual" }).check();
  await page.getByRole("button", { name: "Ir a pagar 100.000 COP" }).click();
  await page.getByRole("button", { name: "Aprobar el pago" }).click();
  await expect(page.getByText("Pago aprobado")).toBeVisible();

  // El administrador sube el precio del plan: la suscripción conserva el suyo.
  const context = await browser.newContext();
  const panel = await context.newPage();
  await loginViaUi(panel, ADMIN_EMAIL, ADMIN_PASSWORD);
  await expect(panel).toHaveURL(/\/dashboard/);
  await panel.goto("/admin/planes");
  const fila = panel.getByTestId(`plan-${code}`);
  await fila.getByRole("button", { name: "Editar" }).click();
  await fila.getByLabel("Precio que se cobra (COP)").fill("120000");
  await fila.getByLabel(`Motivo del cambio en ${code}`).fill("Ajuste de precio de prueba");
  await fila.getByRole("button", { name: "Guardar cambios" }).click();

  const traslado = fila.getByRole("region", { name: "Precio de las suscripciones vigentes" });
  await expect(traslado.getByText(/1 suscripcion sube a 120\.000 COP/)).toBeVisible();

  // Sin motivo y sin confirmar no se traslada.
  const boton = traslado.getByRole("button", { name: "Trasladar el precio a las vigentes" });
  await expect(boton).toBeDisabled();
  await traslado.getByLabel("Motivo del traslado").fill(`Precio nuevo del plan (${email})`);
  await traslado.getByRole("checkbox").check();
  await boton.click();

  const enCurso = traslado.getByTestId("traslado-en-curso");
  await expect(enCurso.getByText(/Traslado en curso a 120\.000 COP/)).toBeVisible();
  await expect(enCurso.getByText("Esperando su aviso")).toBeVisible();

  // Hasta que salga el aviso, el cliente sigue viendo su precio.
  await page.goto("/cuenta");
  const suscripcion = page.getByTestId("suscripcion");
  await expect(suscripcion.getByText(/100\.000 COP \/ mes/)).toBeVisible();
  await expect(suscripcion.getByText("Precio nuevo")).toHaveCount(0);

  // Se cancela, con motivo, y queda en la bitácora.
  await enCurso.getByLabel("Motivo de la cancelación").fill(`Se decidió no subir (${email})`);
  await enCurso.getByRole("button", { name: "Cancelar el traslado" }).click();
  await expect(traslado.getByText(/1 suscripcion sube a 120\.000 COP/)).toBeVisible();

  await panel.goto("/admin/auditoria");
  await expect(
    panel.locator("li", { hasText: `Precio nuevo del plan (${email})` }).getByText(
      "Trasladó el precio a las suscripciones vigentes",
    ),
  ).toBeVisible();
  await expect(
    panel.locator("li", { hasText: `Se decidió no subir (${email})` }).getByText(
      "Canceló un traslado de precio",
    ),
  ).toBeVisible();
  await context.close();
});
