import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import {
  PASSWORD,
  confirmEmail,
  expectEmail,
  loginViaUi,
  registerViaApi,
  uniqueEmail,
} from "./helpers";

/**
 * Gestión de una suscripción ya pagada desde "Mi cuenta" (paso 5 de la Fase 4,
 * entrega 3; §3.6 y §5.4): pasar de un modo de pago al otro, cambiar el medio
 * de pago y eliminar la cuenta con una renovación activa.
 *
 * La API corre con la pasarela simulada: no se cobra nada ni se sale a la red.
 */

async function subscribeManually(page: Page): Promise<void> {
  await page
    .getByRole("article", { name: "Acceso Mensual" })
    .getByRole("link", { name: "Suscribirme" })
    .click();
  await page.getByRole("radio", { name: "Pago manual" }).check();
  await page.getByRole("button", { name: "Ir a pagar 100.000 COP" }).click();
  await page.getByRole("button", { name: "Aprobar el pago" }).click();
  await expect(page.getByText("Pago aprobado")).toBeVisible();
}

async function acceptProcessorTerms(page: Page): Promise<void> {
  await page.getByRole("checkbox", { name: /Acepto los términos de uso de Wompi/ }).check();
  await page.getByRole("checkbox", { name: /tratamiento de mis datos personales/ }).check();
}

test("de pago manual a renovación automática, cambio de medio y vuelta a pago manual", async ({
  page,
  request,
}) => {
  const email = uniqueEmail();
  await registerViaApi(request, email, { access: "ninguno" });
  await confirmEmail(request, email);
  await loginViaUi(page, email);
  await subscribeManually(page);

  // Pagar el siguiente período a mano ofrece también que se renueve sola.
  await page.goto("/planes");
  await page.getByRole("link", { name: /Pagar el siguiente/ }).click();
  await expect(
    page.getByRole("link", { name: "activa la renovación automática desde tu cuenta" }),
  ).toBeVisible();

  await page.goto("/cuenta");
  const suscripcion = page.getByTestId("suscripcion");
  await expect(suscripcion.getByText("Pago manual: no se renueva solo")).toBeVisible();
  await expect(suscripcion.getByText("Próximo cobro")).toHaveCount(0);

  // De manual a automática: sin aceptar los dos documentos no se puede guardar.
  await suscripcion.getByRole("button", { name: "Activar la renovación automática" }).click();
  await expect(suscripcion.getByText(/Hoy no se te cobra nada: ya pagaste hasta el/)).toBeVisible();
  const guardar = suscripcion.getByRole("button", { name: "Guardar medio de pago" });
  await expect(guardar).toBeDisabled();
  await acceptProcessorTerms(page);
  await guardar.click();
  await expect(
    suscripcion.getByText(
      "Renovación automática activada con Visa •••• 4242. Hoy no se te cobró nada.",
    ),
  ).toBeVisible();
  await expect(suscripcion.getByText("Renovación automática", { exact: true })).toBeVisible();
  await expect(suscripcion.getByText(/100\.000 COP, a partir del/)).toBeVisible();
  await expectEmail(email, "Cambió el medio de pago de tu suscripción");

  // El historial sigue con un solo pago: activar la renovación no cobró nada.
  await expect(page.getByTestId("historial-de-pagos").getByRole("listitem")).toHaveCount(1);

  // Un medio que la pasarela no deja guardar: lo dice y todo queda como estaba.
  await suscripcion.getByRole("button", { name: "Cambiar el medio de pago" }).click();
  await expect(suscripcion.getByText(/El medio nuevo reemplaza al que tienes guardado/)).toBeVisible();
  await acceptProcessorTerms(page);
  await page.getByLabel("Medio de pago simulado (solo pruebas)").selectOption("fake-token-rejected");
  await suscripcion.getByRole("button", { name: "Guardar medio de pago" }).click();
  await expect(page.getByText(/no aceptó ese medio de pago/)).toBeVisible();

  // Con uno que sí se puede guardar.
  await page.getByLabel("Medio de pago simulado (solo pruebas)").selectOption("fake-token-ok");
  await suscripcion.getByRole("button", { name: "Guardar medio de pago" }).click();
  await expect(
    suscripcion.getByText("Medio de pago actualizado: Visa •••• 4242. Hoy no se te cobró nada."),
  ).toBeVisible();
  // La confirmación se ve como tal, y la fila del medio de pago lo marca.
  await expect(suscripcion.getByRole("status")).toContainText("Medio de pago actualizado");
  await expect(suscripcion.getByText("Actualizado", { exact: true })).toBeVisible();

  // De automática a manual: pide confirmar, y se puede arrepentir.
  await suscripcion.getByRole("button", { name: "Pasar a pago manual" }).click();
  await suscripcion.getByRole("button", { name: "No, dejarla como está" }).click();
  await expect(suscripcion.getByText("Renovación automática", { exact: true })).toBeVisible();
  await suscripcion.getByRole("button", { name: "Pasar a pago manual" }).click();
  await suscripcion.getByRole("button", { name: "Sí, pasar a pago manual" }).click();
  await expect(suscripcion.getByText(/Tu suscripción pasó a pago manual/)).toBeVisible();
  await expect(suscripcion.getByText("Pago manual: no se renueva solo")).toBeVisible();
  await expect(suscripcion.getByText("Próximo cobro")).toHaveCount(0);
  await expect(suscripcion.getByText("Medio de pago", { exact: true })).toHaveCount(0);
  await expectEmail(email, "pasó a pago manual");

  // Conserva el acceso.
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/dashboard/);
});

test("renovación cancelada: se reanuda con otro medio de pago", async ({ page, request }) => {
  const email = uniqueEmail();
  await registerViaApi(request, email, { access: "ninguno" });
  await confirmEmail(request, email);
  await loginViaUi(page, email);
  await page
    .getByRole("article", { name: "Acceso Mensual" })
    .getByRole("link", { name: "Suscribirme" })
    .click();
  await page.getByRole("radio", { name: "Renovación automática" }).check();
  await acceptProcessorTerms(page);
  await page.getByRole("button", { name: /Guardar medio de pago y pagar/ }).click();
  await expect(page.getByText("Pago aprobado")).toBeVisible();

  await page.goto("/cuenta");
  const suscripcion = page.getByTestId("suscripcion");
  await suscripcion.getByRole("button", { name: "Cancelar la renovación" }).click();
  await suscripcion.getByRole("button", { name: "Sí, cancelar la renovación" }).click();
  await expect(suscripcion.getByText("Renovación cancelada", { exact: true })).toBeVisible();

  await suscripcion.getByRole("button", { name: "Reanudar con otro medio de pago" }).click();
  await acceptProcessorTerms(page);
  await suscripcion.getByRole("button", { name: "Guardar medio de pago" }).click();
  await expect(
    suscripcion.getByText(
      "Renovación automática activada con Visa •••• 4242. Hoy no se te cobró nada.",
    ),
  ).toBeVisible();
  await expect(suscripcion.getByText("Vigente", { exact: true })).toBeVisible();
  await expect(suscripcion.getByText("Próximo cobro")).toBeVisible();
});

test("eliminar la cuenta con renovación automática: avisa qué pasa con la suscripción", async ({
  page,
  request,
}) => {
  const email = uniqueEmail();
  await registerViaApi(request, email, { access: "ninguno" });
  await confirmEmail(request, email);
  await loginViaUi(page, email);
  await page
    .getByRole("article", { name: "Acceso Mensual" })
    .getByRole("link", { name: "Suscribirme" })
    .click();
  await page.getByRole("radio", { name: "Renovación automática" }).check();
  await acceptProcessorTerms(page);
  await page.getByRole("button", { name: /Guardar medio de pago y pagar/ }).click();
  await expect(page.getByText("Pago aprobado")).toBeVisible();

  await page.goto("/cuenta");
  await expect(
    page.getByText(/Si tienes una suscripción, se elimina con la cuenta/),
  ).toBeVisible();
  await page.getByRole("button", { name: "Eliminar mi cuenta" }).click();
  await page.locator("#delete-account-password").fill(PASSWORD);
  await page.getByRole("button", { name: "Eliminar definitivamente" }).click();
  await expect(page).toHaveURL(/\/login/);

  await loginViaUi(page, email);
  await expect(page.getByText("Correo o contraseña incorrectos")).toBeVisible();
  await expectEmail(email, "fue eliminada");
});
