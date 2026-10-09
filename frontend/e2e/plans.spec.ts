import { expect, test } from "@playwright/test";

import {
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  loginViaUi,
  registerViaApi,
  uniqueEmail,
} from "./helpers";

/**
 * Planes y cupones del paso 4 de la Fase 4 (§3.10, §4.4, §4.5). Un error aquí
 * es un precio mal mostrado a quien va a pagar, o un cambio de precio sin
 * rastro en la bitácora.
 */

test("cuenta sin acceso: ve /planes con el precio que se cobra", async ({ page, request }) => {
  const email = uniqueEmail();
  await registerViaApi(request, email, { access: "ninguno" });
  await loginViaUi(page, email);

  // La mesa la manda a los planes.
  await expect(page).toHaveURL(/\/planes/);
  await expect(page.getByRole("heading", { level: 1, name: "Planes" })).toBeVisible();
  await expect(page.getByText("Tu cuenta no tiene acceso activo.")).toBeVisible();

  const plan = page.getByRole("article", { name: "Acceso Mensual" });
  await expect(plan.getByRole("heading", { name: "Acceso Mensual" })).toBeVisible();
  // Lo que se cobra es el protagonista y va con su moneda.
  await expect(plan.getByText("100.000 COP", { exact: true })).toBeVisible();
  await expect(plan.getByText("/ mes")).toBeVisible();
  // Un solo precio: no se muestra ninguna cifra en otra moneda.
  await expect(plan.getByText(/USD/)).toHaveCount(0);
  await expect(
    plan.getByText("El cobro se hace siempre en pesos colombianos (COP).", { exact: false }),
  ).toBeVisible();
  await expect(
    plan.getByText("tu banco convierte los 100.000 COP a tu moneda con su propia tasa", {
      exact: false,
    }),
  ).toBeVisible();
  // La descripción no promete resultados.
  await expect(plan.getByText(/no son una predicción y no cambian la ventaja de la casa/)).toBeVisible();

  // Todavía no se puede pagar: el botón no hace nada.
  await expect(plan.getByRole("button", { name: "Suscribirme" })).toBeDisabled();
  await expect(plan.getByText("El pago estará disponible pronto.")).toBeVisible();

  // La cuenta no queda bloqueada, y volver a la mesa la trae aquí otra vez.
  await page.getByRole("link", { name: "Mi cuenta" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mi cuenta" })).toBeVisible();
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/planes/);
});

test("/planes es pública: se ve sin sesión", async ({ page }) => {
  await page.goto("/planes");
  const plan = page.getByRole("article", { name: "Acceso Mensual" });
  await expect(plan.getByText("100.000 COP", { exact: true })).toBeVisible();
  await expect(page.getByText(/USD/)).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Crear cuenta" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Entrar" })).toBeVisible();
  await expect(page.getByText("Tu cuenta no tiene acceso activo.")).toHaveCount(0);
});

test("cuenta con acceso: /planes la devuelve a la mesa", async ({ page, request }) => {
  const email = uniqueEmail();
  await registerViaApi(request, email);
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/dashboard/);
  await page.goto("/planes");
  await expect(page.getByText("Tu cuenta ya tiene acceso.")).toBeVisible();
  await page.getByRole("link", { name: "Ir a la mesa" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
});

test("el administrador crea, edita y desactiva un plan, con motivo y bitácora", async ({
  page,
  browser,
}) => {
  const sufijo = Math.random().toString(36).slice(2, 8);
  const code = `e2e-${sufijo}`;
  const name = `Plan de prueba ${sufijo}`;

  await loginViaUi(page, ADMIN_EMAIL, ADMIN_PASSWORD);
  await expect(page).toHaveURL(/\/dashboard/);
  await page.goto("/admin/planes");
  await expect(page.getByRole("heading", { level: 1, name: "Planes" })).toBeVisible();

  // El plan sembrado, con lo que se cobra.
  const mensual = page.getByTestId("plan-mensual");
  await expect(mensual.getByText(/Se cobra 100\.000 COP \/ mes/)).toBeVisible();

  // Crea uno nuevo.
  const nuevo = page.locator("section", { hasText: "Nuevo plan" });
  await nuevo.getByLabel("Código").fill(code);
  await nuevo.getByLabel("Nombre").fill(name);
  await nuevo.getByLabel("Descripción").fill("Acceso a la plataforma. Solo para un test.");
  await nuevo.getByLabel("Precio que se cobra (COP)").fill("50000");
  await nuevo.getByLabel("Orden en la página").fill("900");
  await nuevo.getByLabel("Motivo de la creación").fill("Plan de un test de punta a punta");
  await nuevo.getByRole("button", { name: "Crear plan" }).click();
  await expect(nuevo.getByText("Plan creado")).toBeVisible();

  const fila = page.getByTestId(`plan-${code}`);
  await expect(fila.getByText(/Se cobra 50\.000 COP \/ mes/)).toBeVisible();
  await expect(fila.getByText("Activo", { exact: true })).toBeVisible();

  // El público ya lo ve.
  const publico = await browser.newContext();
  const visita = await publico.newPage();
  await visita.goto("/planes");
  await expect(
    visita.getByRole("article", { name }).getByText("50.000 COP", { exact: true }),
  ).toBeVisible();

  // Le cambia el precio.
  await fila.getByRole("button", { name: "Editar" }).click();
  await fila.getByLabel("Precio que se cobra (COP)").fill("60000");
  // Sin motivo no se guarda.
  await fila.getByRole("button", { name: "Guardar cambios" }).click();
  await expect(fila.getByText("Plan actualizado")).toHaveCount(0);
  await fila.getByLabel(`Motivo del cambio en ${code}`).fill("Ajuste de precio de prueba");
  await fila.getByRole("button", { name: "Guardar cambios" }).click();
  await expect(fila.getByText("Plan actualizado")).toBeVisible();
  await expect(fila.getByText(/Se cobra 60\.000 COP \/ mes/)).toBeVisible();

  // Lo desactiva: deja de ofrecerse, pero no se borra.
  await fila.getByLabel(`Motivo del cambio en ${code}`).fill("Fin de la prueba");
  await fila.getByRole("button", { name: "Desactivar plan" }).click();
  await expect(fila.getByText("Desactivado", { exact: true })).toBeVisible();
  await visita.reload();
  await expect(visita.getByRole("article", { name: "Acceso Mensual" })).toBeVisible();
  await expect(visita.getByRole("article", { name })).toHaveCount(0);
  await publico.close();

  // Los tres cambios quedaron en la bitácora, con su motivo.
  await page.goto("/admin/auditoria");
  const precio = page.locator("li", { hasText: "Ajuste de precio de prueba" });
  await expect(precio.getByText("Editó un plan")).toBeVisible();
  await expect(precio.getByText(/price_cents: 5000000/)).toBeVisible();
  await expect(precio.getByText(/price_cents: 6000000/)).toBeVisible();
  await expect(
    page.locator("li", { hasText: "Plan de un test de punta a punta" }).getByText("Creó un plan"),
  ).toBeVisible();
  await expect(page.locator("li", { hasText: "Fin de la prueba" }).getByText("Editó un plan")).toBeVisible();
});

test("el administrador crea y desactiva un cupón; un código que promete resultados se rechaza", async ({
  page,
}) => {
  const code = `E2E-${Math.random().toString(36).slice(2, 8).toUpperCase()}`;

  await loginViaUi(page, ADMIN_EMAIL, ADMIN_PASSWORD);
  await expect(page).toHaveURL(/\/dashboard/);
  await page.goto("/admin/descuentos");
  await expect(page.getByRole("heading", { level: 1, name: "Descuentos" })).toBeVisible();

  const nuevo = page.locator("section", { hasText: "Nuevo cupón" });
  const motivo = nuevo.getByLabel("Motivo de la creación");

  // Ningún código promete resultados.
  await nuevo.getByLabel("Código").fill("GANASEGURO");
  await nuevo.getByLabel("Porcentaje (1 a 99)").fill("10");
  await motivo.fill("Cupón de un test de punta a punta");
  await nuevo.getByRole("button", { name: "Crear cupón" }).click();
  await expect(nuevo.getByText(/ningún cupón promete resultados/)).toBeVisible();

  // Tampoco existe el cupón del 100 %.
  await nuevo.getByLabel("Código").fill(code.toLowerCase());
  await nuevo.getByLabel("Porcentaje (1 a 99)").fill("100");
  await nuevo.getByRole("button", { name: "Crear cupón" }).click();
  await expect(nuevo.getByText("El porcentaje va de 1 a 99")).toBeVisible();

  await nuevo.getByLabel("Porcentaje (1 a 99)").fill("15");
  await nuevo.getByLabel("Tope de usos (opcional)").fill("20");
  await nuevo.getByRole("button", { name: "Crear cupón" }).click();
  await expect(nuevo.getByText("Cupón creado")).toBeVisible();

  // Se guardó en mayúsculas y se encuentra por código.
  await page.getByLabel("Buscar por código").fill(code.toLowerCase());
  await page.getByRole("button", { name: "Buscar" }).click();
  const fila = page.getByTestId(`cupon-${code}`);
  await expect(fila.getByText("15 % en el primer cobro · Usos: 0 de 20")).toBeVisible();
  await expect(fila.getByText("Activo", { exact: true })).toBeVisible();

  await fila.getByRole("button", { name: "Ver" }).click();
  await expect(fila.getByText("Nadie ha usado este cupón.")).toBeVisible();

  // Sube el descuento, con motivo.
  await fila.getByLabel("Porcentaje (1 a 99)").fill("25");
  await fila.getByLabel(`Motivo del cambio en ${code}`).fill("Sube el descuento de prueba");
  await fila.getByRole("button", { name: "Guardar cambios" }).click();
  await expect(fila.getByText("Cupón actualizado")).toBeVisible();
  await expect(fila.getByText("25 % en el primer cobro · Usos: 0 de 20")).toBeVisible();

  // Lo desactiva.
  await fila.getByLabel(`Motivo del cambio en ${code}`).fill("Fin de la prueba del cupón");
  await fila.getByRole("button", { name: "Desactivar cupón" }).click();
  await expect(fila.getByText("Desactivado", { exact: true })).toBeVisible();
  await expect(fila.getByRole("button", { name: "Activar cupón" })).toBeVisible();

  await page.goto("/admin/auditoria");
  const cambio = page.locator("li", { hasText: "Sube el descuento de prueba" });
  await expect(cambio.getByText("Editó un cupón")).toBeVisible();
  await expect(cambio.getByText(/value: 15/)).toBeVisible();
  await expect(cambio.getByText(/value: 25/)).toBeVisible();
  await expect(
    page.locator("li", { hasText: "Cupón de un test de punta a punta" }).getByText("Creó un cupón"),
  ).toBeVisible();
});
