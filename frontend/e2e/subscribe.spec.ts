import { expect, test } from "@playwright/test";

import {
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  confirmEmail,
  createPercentCoupon,
  expectEmail,
  grantAccess,
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

test("cuenta sin acceso: se suscribe con cupón y entra a la mesa", async ({
  page,
  request,
  browser,
}) => {
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

  // Ningún modo entra marcado: hasta elegir, no se puede pagar.
  await expect(page.getByRole("button", { name: "Ir a pagar 80.000 COP" })).toBeDisabled();
  await expect(page.getByText("Elige cómo quieres pagar para continuar.")).toBeVisible();
  await expect(page.getByRole("radio", { name: "Pago manual" })).not.toBeChecked();
  await expect(page.getByRole("radio", { name: "Renovación automática" })).not.toBeChecked();
  await page.getByRole("radio", { name: "Pago manual" }).check();
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
  await expect(page.getByRole("radio", { name: "Renovación automática" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Ir a pagar 100.000 COP" })).toBeEnabled();

  // Mi cuenta: la suscripción y el pago que acaba de hacer.
  await page.goto("/cuenta");
  const suscripcion = page.getByTestId("suscripcion");
  await expect(suscripcion.getByText("Acceso Mensual")).toBeVisible();
  await expect(suscripcion.getByText("Vigente", { exact: true })).toBeVisible();
  await expect(suscripcion.getByText("Acceso hasta")).toBeVisible();
  // El precio congelado es el del plan, no el del primer cobro con cupón.
  await expect(suscripcion.getByText("100.000 COP / mes")).toBeVisible();
  await expect(suscripcion.getByText("Pago manual: no se renueva solo")).toBeVisible();
  await expect(suscripcion.getByRole("link", { name: "paga el siguiente período" })).toBeVisible();
  const historial = page.getByTestId("historial-de-pagos");
  await expect(historial.getByText("80.000 COP · Acceso Mensual")).toBeVisible();
  await expect(historial.getByText("Aprobado", { exact: true })).toBeVisible();

  // El administrador la encuentra por su suscripción y ve qué pagó.
  const adminContext = await browser.newContext();
  const admin = await adminContext.newPage();
  await loginViaUi(admin, ADMIN_EMAIL, ADMIN_PASSWORD);
  await expect(admin).toHaveURL(/\/dashboard/);
  await admin.goto("/admin/usuarios");
  await admin.getByLabel("Buscar por correo o nombre").fill(email);
  await admin.getByLabel("Suscripción").selectOption("lapsed");
  await admin.getByRole("button", { name: "Buscar" }).click();
  await expect(admin.getByText("Ninguna cuenta coincide con la búsqueda.")).toBeVisible();
  await admin.getByLabel("Suscripción").selectOption("in_force");
  await admin.getByRole("button", { name: "Buscar" }).click();
  await expect(admin.getByText(email)).toBeVisible();
  await admin.getByRole("button", { name: "Ver", exact: true }).click();

  const cobros = admin.getByTestId("suscripcion-y-pagos");
  await expect(cobros.getByText(/Acceso Mensual · activa · vigente, hasta el/)).toBeVisible();
  await expect(cobros.getByText(/con descuento de 20\.000 COP/)).toBeVisible();
  await expect(cobros.getByText("Aprobado", { exact: true })).toBeVisible();
  await expect(cobros.getByText(/referencia SA-/)).toBeVisible();
  await expect(cobros.getByText(/transacción fake-/)).toBeVisible();
  // El formulario de acceso manual explica qué hace sobre una cuenta que paga.
  await expect(admin.getByText("Esta cuenta tiene una suscripción vigente.")).toBeVisible();
  await expect(admin.getByText(/Para sacarla de la mesa, suspende la cuenta/)).toBeVisible();
  await adminContext.close();
});

test("suscriptor con acceso manual: /planes no le ofrece un pago que se rechazaría", async ({
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
  await page.getByRole("radio", { name: "Pago manual" }).check();
  await page.getByRole("button", { name: "Ir a pagar 100.000 COP" }).click();
  await page.getByRole("button", { name: "Aprobar el pago" }).click();
  await expect(page.getByText("Pago aprobado")).toBeVisible();

  // Un administrador le da además acceso manual.
  await grantAccess(request, email);

  await page.goto("/planes");
  const mensual = page.getByRole("article", { name: "Acceso Mensual" });
  await expect(mensual.getByText("Tu plan actual")).toBeVisible();
  await expect(mensual.getByText(/mientras lo tenga no necesitas pagar otro período/)).toBeVisible();
  await expect(page.getByRole("link", { name: /Suscribirme|Pagar el siguiente/ })).toHaveCount(0);

  await page.goto("/cuenta");
  const suscripcion = page.getByTestId("suscripcion");
  await expect(suscripcion.getByText("Vigente", { exact: true })).toBeVisible();
  await expect(suscripcion.getByText(/acceso otorgado por un administrador/)).toBeVisible();
  await expect(suscripcion.getByRole("link", { name: "paga el siguiente período" })).toHaveCount(0);
});

test("cuenta que nunca ha pagado: Mi cuenta lo dice y lleva a los planes", async ({
  page,
  request,
}) => {
  const email = uniqueEmail();
  await registerViaApi(request, email, { access: "ninguno" });
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/planes/);
  await page.goto("/cuenta");
  await expect(page.getByText("No tienes una suscripción.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Ver los planes" })).toBeVisible();
  await expect(page.getByText("Todavía no hay pagos en tu cuenta.")).toBeVisible();
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
  await page.getByRole("radio", { name: "Pago manual" }).check();
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

test("renovación automática: guarda el medio, entra a la mesa, cancela y reanuda", async ({
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
  await expect(page.getByTestId("total-a-pagar")).toHaveText("100.000 COP");

  await page.getByRole("radio", { name: "Renovación automática" }).check();
  await expect(page.getByText(/Antes de cada cobro te avisamos por correo/)).toBeVisible();
  // Sin aceptar los dos documentos del procesador no se puede guardar el medio.
  const guardar = page.getByRole("button", { name: "Guardar medio de pago y pagar 100.000 COP" });
  await expect(guardar).toBeDisabled();
  await page.getByRole("checkbox", { name: /Acepto los términos de uso de Wompi/ }).check();
  await expect(guardar).toBeDisabled();
  await page.getByRole("checkbox", { name: /tratamiento de mis datos personales/ }).check();
  await expect(page.getByText(/solo la referencia que entrega Wompi/)).toBeVisible();
  await guardar.click();

  await expect(page).toHaveURL(/\/pago\/[0-9a-f-]+$/);
  await expect(page.getByText("Pago aprobado")).toBeVisible();
  await page.getByRole("link", { name: "Ir a la mesa" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  await expectEmail(email, "Tu suscripción a Sebasanálisis está activa");

  // /planes no le ofrece pagar: se renueva sola.
  await page.goto("/planes");
  const mensual = page.getByRole("article", { name: "Acceso Mensual" });
  await expect(mensual.getByText("Tu plan actual")).toBeVisible();
  await expect(mensual.getByText(/Se renueva sola/)).toBeVisible();
  await expect(page.getByRole("link", { name: /Suscribirme|Pagar el siguiente/ })).toHaveCount(0);

  // Mi cuenta: el medio guardado (sin el número), el próximo cobro y cancelar.
  await page.goto("/cuenta");
  const suscripcion = page.getByTestId("suscripcion");
  await expect(suscripcion.getByText("Renovación automática", { exact: true })).toBeVisible();
  await expect(suscripcion.getByText("Visa •••• 4242")).toBeVisible();
  await expect(suscripcion.getByText(/100\.000 COP, a partir del/)).toBeVisible();

  await suscripcion.getByRole("button", { name: "Cancelar la renovación" }).click();
  // Pide confirmar, y se puede arrepentir.
  await suscripcion.getByRole("button", { name: "No, dejarla como está" }).click();
  await expect(suscripcion.getByText("Vigente", { exact: true })).toBeVisible();
  await suscripcion.getByRole("button", { name: "Cancelar la renovación" }).click();
  await suscripcion.getByRole("button", { name: "Sí, cancelar la renovación" }).click();
  await expect(suscripcion.getByText("Renovación cancelada", { exact: true })).toBeVisible();
  await expect(suscripcion.getByText("Renovación cancelada. No te vamos a hacer más cobros.")).toBeVisible();
  await expect(suscripcion.getByText("Próximo cobro")).toHaveCount(0);
  await expectEmail(email, "Cancelaste la renovación de tu suscripción");

  // Conserva el acceso hasta el fin del período.
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/dashboard/);

  await page.goto("/cuenta");
  await page.getByTestId("suscripcion").getByRole("button", { name: "Reanudar la renovación" }).click();
  await expect(page.getByTestId("suscripcion").getByText("Vigente", { exact: true })).toBeVisible();
  await expect(page.getByTestId("suscripcion").getByText("Próximo cobro")).toBeVisible();
});

test("renovación automática: primer cobro rechazado no da acceso", async ({ page, request }) => {
  const email = uniqueEmail();
  await registerViaApi(request, email, { access: "ninguno" });
  await confirmEmail(request, email);
  await loginViaUi(page, email);
  await page
    .getByRole("article", { name: "Acceso Mensual" })
    .getByRole("link", { name: "Suscribirme" })
    .click();
  await page.getByRole("radio", { name: "Renovación automática" }).check();
  await page.getByRole("checkbox", { name: /Acepto los términos de uso de Wompi/ }).check();
  await page.getByRole("checkbox", { name: /tratamiento de mis datos personales/ }).check();

  // Un medio que la pasarela no deja guardar: se dice aquí mismo y no pasa nada más.
  await page.getByLabel("Medio de pago simulado (solo pruebas)").selectOption("fake-token-rejected");
  await page.getByRole("button", { name: /Guardar medio de pago y pagar/ }).click();
  await expect(page.getByText(/no aceptó ese medio de pago/)).toBeVisible();
  await expect(page).toHaveURL(/\/planes\/pagar/);

  // Uno que se guarda pero cuyo cobro se rechaza.
  await page.getByLabel("Medio de pago simulado (solo pruebas)").selectOption("fake-token-declined");
  await page.getByRole("button", { name: /Guardar medio de pago y pagar/ }).click();
  await expect(page.getByText("El pago no se completó")).toBeVisible();
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/planes/);
});
