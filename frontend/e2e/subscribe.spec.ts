import { expect, test } from "@playwright/test";

import {
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  confirmEmail,
  createPercentCoupon,
  expectEmail,
  loginViaUi,
  registerViaApi,
  uniqueEmail,
} from "./helpers";

/**
 * Alta con pago manual (paso 5 de la Fase 4, entrega 1; §3.4 y §3.9).
 *
 * La API corre con la pasarela simulada (`PAYMENT_PROVIDER=fake`): el botón de
 * pagar lleva a una página suya con "aprobar" y "rechazar". No se cobra nada ni
 * se sale a la red, y el resto del recorrido es el de verdad: el total lo
 * calcula el servidor y el acceso solo aparece cuando el servidor reconsulta
 * la transacción.
 */

test("cuenta sin acceso: se suscribe con cupón y entra a la mesa", async ({ page, request }) => {
  const email = uniqueEmail();
  await registerViaApi(request, email, { access: "ninguno" });
  await confirmEmail(request, email);
  const cupon = await createPercentCoupon(request, 20);

  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/planes/);
  await expect(page.getByText("Tu cuenta no tiene acceso activo.")).toBeVisible();

  await page
    .getByRole("article", { name: "Acceso Mensual" })
    .getByRole("link", { name: "Suscribirme" })
    .click();
  await expect(page).toHaveURL(/\/planes\/pagar\?plan=/);
  await expect(page.getByRole("heading", { level: 1, name: "Confirma tu pago" })).toBeVisible();

  // El total lo dice el servidor, en la moneda en que se cobra y solo en esa.
  const total = page.getByTestId("total-a-pagar");
  await expect(total).toHaveText("100.000 COP");
  await expect(page.getByText(/USD/)).toHaveCount(0);
  await expect(
    page.getByText(
      "Cobro en pesos colombianos (COP). Con tarjeta de otro país, tu banco aplica su tasa de cambio y puede cobrar comisiones.",
    ),
  ).toBeVisible();
  await expect(page.getByText(/no cambia el resultado de ningún juego/)).toBeVisible();

  // Un código que no existe: lo dice y el total no cambia.
  await page.getByLabel("Cupón (opcional)").fill("NO-EXISTE");
  await page.getByRole("button", { name: "Aplicar" }).click();
  await expect(page.getByText("Ese código no existe.")).toBeVisible();
  await expect(total).toHaveText("100.000 COP");

  // El cupón de verdad: 20 % menos.
  await page.getByLabel("Cupón (opcional)").fill(cupon.toLowerCase());
  await page.getByRole("button", { name: "Aplicar" }).click();
  await expect(page.getByText(`Cupón ${cupon} aplicado.`)).toBeVisible();
  await expect(total).toHaveText("80.000 COP");
  const resumen = page.getByTestId("resumen-pago");
  await expect(resumen.getByText("100.000 COP")).toBeVisible();
  await expect(resumen.getByText("− 20.000 COP")).toBeVisible();

  await page.getByRole("button", { name: "Ir a pagar 80.000 COP" }).click();

  // La pasarela simulada recibe el monto del servidor, no uno del navegador.
  await expect(page.getByRole("heading", { name: "Pasarela simulada" })).toBeVisible();
  await expect(page.getByText("Monto: 8000000 centavos COP")).toBeVisible();
  await page.getByRole("button", { name: "Aprobar el pago" }).click();

  // De vuelta: la pantalla espera a que el servidor confirme.
  await expect(page).toHaveURL(/\/pago\/[0-9a-f-]+\?id=fake-/);
  await expect(page.getByText("Pago aprobado")).toBeVisible();
  await expect(page.getByText("80.000 COP")).toBeVisible();
  await expect(page.getByText("Acceso hasta")).toBeVisible();

  await page.getByRole("link", { name: "Ir a la mesa" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  // Entró: ya no la devuelve a los planes.
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/dashboard/);

  await expectEmail(email, "Tu suscripción a Sebasanálisis está activa");
  await expectEmail(email, "Recibo de tu pago en Sebasanálisis");

  // /planes ya no le ofrece suscribirse: le muestra su plan.
  await page.goto("/planes");
  const mensual = page.getByRole("article", { name: "Acceso Mensual" });
  await expect(mensual.getByText("Tu plan actual")).toBeVisible();
  await expect(mensual.getByText(/Tienes acceso hasta el/)).toBeVisible();
  await expect(mensual.getByRole("link", { name: "Pagar el siguiente período" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Suscribirme" })).toHaveCount(0);
  const bimestral = page.getByRole("article", { name: "Acceso Bimestral" });
  await expect(bimestral.getByText("Tu plan actual")).toHaveCount(0);
  await expect(bimestral.getByText(/Para cambiar de plan/)).toBeVisible();

  // El período siguiente: sin cupón y contando desde el vencimiento.
  await mensual.getByRole("link", { name: "Pagar el siguiente período" }).click();
  await expect(page.getByText(/El período nuevo empieza ese día/)).toBeVisible();
  await expect(page.getByLabel("Cupón (opcional)")).toHaveCount(0);
  await expect(page.getByTestId("total-a-pagar")).toHaveText("100.000 COP");
});

test("pago rechazado: no hay acceso y se puede volver a intentar", async ({ page, request }) => {
  const email = uniqueEmail();
  await registerViaApi(request, email, { access: "ninguno" });
  await confirmEmail(request, email);
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/planes/);

  await page
    .getByRole("article", { name: "Acceso Bimestral" })
    .getByRole("link", { name: "Suscribirme" })
    .click();
  await expect(page.getByTestId("total-a-pagar")).toHaveText("150.000 COP");
  await page.getByRole("button", { name: "Ir a pagar 150.000 COP" }).click();
  await page.getByRole("button", { name: "Rechazar el pago" }).click();

  await expect(page.getByText("El pago no se completó")).toBeVisible();
  await expect(page.getByText(/fue rechazado y tu suscripción no se activó/)).toBeVisible();

  // Sigue sin acceso: la mesa la devuelve a los planes, y puede intentarlo otra vez.
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/planes/);
  await expect(
    page.getByRole("article", { name: "Acceso Mensual" }).getByRole("link", { name: "Suscribirme" }),
  ).toBeVisible();
});

test("sin correo confirmado no se puede pagar", async ({ page, request }) => {
  const email = uniqueEmail();
  await registerViaApi(request, email, { access: "ninguno" });
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/planes/);

  await page
    .getByRole("article", { name: "Acceso Mensual" })
    .getByRole("link", { name: "Suscribirme" })
    .click();
  await expect(page.getByTestId("total-a-pagar")).toHaveText("100.000 COP");
  await expect(page.getByRole("button", { name: /Ir a pagar/ })).toBeDisabled();
  await expect(page.getByText("Confirma tu correo para poder pagar.")).toBeVisible();
});

test("el administrador ve los planes sin la opción de suscribirse", async ({ page }) => {
  // El administrador sembrado no ha aceptado los documentos legales: aun así,
  // a un administrador no se le ofrece pagar. (La cuenta con acceso manual y
  // todo aceptado está en plans.spec.ts.)
  await loginViaUi(page, ADMIN_EMAIL, ADMIN_PASSWORD);
  await expect(page).toHaveURL(/\/dashboard/);
  await page.goto("/planes");

  await expect(page.getByRole("heading", { level: 1, name: "Planes" })).toBeVisible();
  await expect(page.getByText("Tu cuenta no tiene acceso activo.")).toHaveCount(0);
  const mensual = page.getByRole("article", { name: "Acceso Mensual" });
  await expect(mensual.getByText("100.000 COP", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /Suscribirme|Pagar/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Suscribirme|Pagar/ })).toHaveCount(0);
  await expect(page.getByText("Tu plan actual")).toHaveCount(0);
});
