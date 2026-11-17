import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import {
  chooseFakeCard,
  PASSWORD,
  confirmEmail,
  expectEmail,
  loginViaUi,
  registerViaApi,
  uniqueEmail,
} from "./helpers";

/**
 * Gestión de una suscripción ya pagada desde "Mi cuenta" (paso 5 de la Fase 4,
 * entrega 3; §3.6 y §5.4): pasar de un modo de pago al otro, cambiar la
 * tarjeta y eliminar la cuenta con una renovación activa. La tarjeta se guarda
 * en la página del procesador (paso 5.3b) y la cuenta la lee al volver.
 *
 * La API corre con la pasarela simulada: no se cobra nada ni se sale a la red.
 */

async function subscribeManually(page: Page): Promise<void> {
  await page
    .getByRole("article", { name: "Acceso Mensual" })
    .getByRole("link", { name: "Suscribirme" })
    .click();
  await page.getByRole("radio", { name: "Pago manual" }).check();
  await chooseFakeCard(page);
  await page.getByRole("button", { name: "Ir a pagar 32 EUR" }).click();
  await page.getByRole("button", { name: "Aprobar el pago" }).click();
  await expect(page.getByText("Pago aprobado")).toBeVisible();
}

test("de pago manual a renovación automática, cambio de tarjeta y vuelta a pago manual", async ({
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

  // De manual a automática: la tarjeta se verifica en la página del procesador
  // y no se cobra nada hoy.
  await suscripcion.getByRole("button", { name: "Activar la renovación automática" }).click();
  await expect(suscripcion.getByText(/Hoy no se te cobra nada: ya pagaste hasta el/)).toBeVisible();
  await suscripcion.getByRole("button", { name: "Ir a guardar la tarjeta" }).click();
  await expect(page.getByText(/Cada renovación \(hoy no se cobra\): 32.00 EUR/)).toBeVisible();
  await page.getByRole("button", { name: "Pagar y guardar la tarjeta" }).click();
  await expect(page).toHaveURL(/\/cuenta$/);
  await expect(
    suscripcion.getByText(
      "Renovación automática activada con Visa •••• 4242. Hoy no se te cobró nada.",
    ),
  ).toBeVisible();
  await expect(suscripcion.getByText("Renovación automática", { exact: true })).toBeVisible();
  await expect(suscripcion.getByText(/32 EUR, a partir del/)).toBeVisible();
  await expectEmail(email, "Cambió el medio de pago de tu suscripción");

  // El historial sigue con un solo pago: activar la renovación no cobró nada.
  await expect(page.getByTestId("historial-de-pagos").getByRole("listitem")).toHaveCount(1);

  // Volver del procesador sin guardar nada: lo dice y todo queda como estaba.
  await page.goto("/cuenta?tarjeta=no-guardada");
  await expect(
    suscripcion.getByText("No se guardó ninguna tarjeta. Tu suscripción sigue como estaba."),
  ).toBeVisible();
  await expect(suscripcion.getByText("Visa •••• 4242")).toBeVisible();

  // Cambiar la tarjeta: otra vez en la página del procesador.
  await suscripcion.getByRole("button", { name: "Cambiar la tarjeta" }).click();
  await expect(suscripcion.getByText(/La tarjeta nueva reemplaza a la que tienes guardada/)).toBeVisible();
  await suscripcion.getByRole("button", { name: "Ir a guardar la tarjeta" }).click();
  await page.getByRole("button", { name: "Guardar la tarjeta", exact: true }).click();
  await expect(page).toHaveURL(/\/cuenta$/);
  await expect(
    suscripcion.getByText("Tarjeta actualizada: Mastercard •••• 5454. Hoy no se te cobró nada."),
  ).toBeVisible();
  // La confirmación se ve como tal, y la fila del medio de pago lo marca.
  await expect(suscripcion.getByRole("status")).toContainText("Tarjeta actualizada");
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

test("renovación cancelada: se reanuda con otra tarjeta", async ({ page, request }) => {
  const email = uniqueEmail();
  await registerViaApi(request, email, { access: "ninguno" });
  await confirmEmail(request, email);
  await loginViaUi(page, email);
  await page
    .getByRole("article", { name: "Acceso Mensual" })
    .getByRole("link", { name: "Suscribirme" })
    .click();
  await page.getByRole("radio", { name: "Renovación automática" }).check();
  await page.getByRole("button", { name: "Ir a pagar 32 EUR con tarjeta" }).click();
  await page.getByRole("button", { name: "Pagar y guardar la tarjeta" }).click();
  await expect(page.getByText("Pago aprobado")).toBeVisible();

  await page.goto("/cuenta");
  const suscripcion = page.getByTestId("suscripcion");
  await suscripcion.getByRole("button", { name: "Cancelar la renovación" }).click();
  await suscripcion.getByRole("button", { name: "Sí, cancelar la renovación" }).click();
  await expect(suscripcion.getByText("Renovación cancelada", { exact: true })).toBeVisible();

  await suscripcion.getByRole("button", { name: "Reanudar con otra tarjeta" }).click();
  await suscripcion.getByRole("button", { name: "Ir a guardar la tarjeta" }).click();
  await page.getByRole("button", { name: "Guardar la tarjeta", exact: true }).click();
  await expect(page).toHaveURL(/\/cuenta$/);
  await expect(
    suscripcion.getByText(
      "Renovación automática activada con Mastercard •••• 5454. Hoy no se te cobró nada.",
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
  await page.getByRole("button", { name: "Ir a pagar 32 EUR con tarjeta" }).click();
  await page.getByRole("button", { name: "Pagar y guardar la tarjeta" }).click();
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
