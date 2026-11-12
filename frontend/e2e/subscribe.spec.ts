import { expect, test } from "@playwright/test";

import {
  chooseFakeCard,
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
  await expect(total).toHaveText("32 EUR");
  await expect(page.getByText(/USD/)).toHaveCount(0);
  await expect(
    page.getByText(
      "Cobro en euros (EUR). Con tarjeta o Bizum pagas en euros; si tu tarjeta es de otro país, tu banco aplica su tasa de cambio y puede cobrar comisiones. Con un medio de pago local pagas en la moneda de tu país: la pasarela hace la conversión y puede sumar un recargo por ella.",
    ),
  ).toBeVisible();

  // Un código que no existe: lo dice y el total no cambia.
  await page.getByLabel("Cupón (opcional)").fill("NO-EXISTE");
  await page.getByRole("button", { name: "Aplicar" }).click();
  await expect(page.getByText("Ese código no existe.")).toBeVisible();
  await expect(total).toHaveText("32 EUR");

  // El cupón de verdad: 20 % menos.
  await page.getByLabel("Cupón (opcional)").fill(cupon.toLowerCase());
  await page.getByRole("button", { name: "Aplicar" }).click();
  await expect(page.getByText(`Cupón ${cupon} aplicado.`)).toBeVisible();
  await expect(total).toHaveText("25,60 EUR");
  const resumen = page.getByTestId("resumen-pago");
  await expect(resumen.getByText("32 EUR")).toBeVisible();
  await expect(resumen.getByText("− 6,40 EUR")).toBeVisible();

  // Ningún modo entra marcado: hasta elegir, no se puede pagar.
  await expect(page.getByRole("button", { name: "Ir a pagar 25,60 EUR" })).toBeDisabled();
  await expect(page.getByText("Elige cómo quieres pagar para continuar.")).toBeVisible();
  await expect(page.getByRole("radio", { name: "Pago manual" })).not.toBeChecked();
  await expect(page.getByRole("radio", { name: "Renovación automática" })).not.toBeChecked();
  await page.getByRole("radio", { name: "Pago manual" }).check();
  await chooseFakeCard(page);
  await page.getByRole("button", { name: "Ir a pagar 25,60 EUR" }).click();

  // La pasarela simulada recibe el monto del servidor, no uno del navegador.
  await expect(page.getByRole("heading", { name: "Pasarela simulada" })).toBeVisible();
  await expect(page.getByText("Monto: 25.60 EUR")).toBeVisible();
  await page.getByRole("button", { name: "Aprobar el pago" }).click();

  // De vuelta: la pantalla espera a que el servidor confirme.
  await expect(page).toHaveURL(/\/pago\/[0-9a-f-]+\?id=fake-/);
  await expect(page.getByText("Pago aprobado")).toBeVisible();
  await expect(page.getByText("25,60 EUR")).toBeVisible();
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
  await expect(page.getByTestId("total-a-pagar")).toHaveText("32 EUR");
  await expect(page.getByRole("radio", { name: "Renovación automática" })).toHaveCount(0);
  // Con pago manual, hasta elegir el país y el medio no se puede pagar.
  await expect(page.getByRole("button", { name: "Ir a pagar 32 EUR" })).toBeDisabled();
  await chooseFakeCard(page);
  await expect(page.getByRole("button", { name: "Ir a pagar 32 EUR" })).toBeEnabled();

  // Mi cuenta: la suscripción y el pago que acaba de hacer.
  await page.goto("/cuenta");
  const suscripcion = page.getByTestId("suscripcion");
  await expect(suscripcion.getByText("Acceso Mensual")).toBeVisible();
  await expect(suscripcion.getByText("Vigente", { exact: true })).toBeVisible();
  await expect(suscripcion.getByText("Acceso hasta")).toBeVisible();
  // El precio congelado es el del plan, no el del primer cobro con cupón.
  await expect(suscripcion.getByText("32 EUR / mes")).toBeVisible();
  await expect(suscripcion.getByText("Pago manual: no se renueva solo")).toBeVisible();
  await expect(suscripcion.getByRole("link", { name: "paga el siguiente período" })).toBeVisible();
  const historial = page.getByTestId("historial-de-pagos");
  await expect(historial.getByText("25,60 EUR · Acceso Mensual")).toBeVisible();
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
  await expect(cobros.getByText(/con descuento de 6,40 EUR/)).toBeVisible();
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
  await chooseFakeCard(page);
  await page.getByRole("button", { name: "Ir a pagar 32 EUR" }).click();
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
  await expect(page.getByTestId("total-a-pagar")).toHaveText("46 EUR");
  await page.getByRole("radio", { name: "Pago manual" }).check();
  await chooseFakeCard(page);
  await page.getByRole("button", { name: "Ir a pagar 46 EUR" }).click();
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

test("el regreso de Redsys: sus parámetros salen de la barra de direcciones", async ({ page }) => {
  // Lo que agrega Redsys al volver a `url_ok`/`url_ko` (sandbox, 2026-11-05).
  const pago = "/pago/0b6f3c1e-2a4d-4e8f-9c7b-5d1a2e3f4a5b";
  const redsys =
    "Ds_SignatureVersion=HMAC_SHA256_V1&Ds_MerchantParameters=eyJEc19DYXJkX0JyYW5kIjoiMSJ9&Ds_Signature=abc%3D";

  await page.goto(`${pago}?${redsys}`);
  await expect(page.getByText("Inicia sesión para ver el resultado de tu pago.")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`${pago}$`));

  // El `?id=` de la pasarela simulada se queda: es lo que se reconsulta.
  await page.goto(`${pago}?id=fake-123&${redsys}`);
  await expect(page).toHaveURL(new RegExp(`${pago}\\?id=fake-123$`));
});

test("medio local: pide el nombre, y la página de pago se abre una sola vez", async ({
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
  const pagar = page.getByRole("button", { name: "Ir a pagar 32 EUR" });

  // Sin país no hay medios; con Colombia aparece el medio local.
  await expect(page.getByRole("radio", { name: "Medio local simulado" })).toHaveCount(0);
  await page.getByLabel("País desde el que pagas").selectOption("CO");
  await page.getByRole("radio", { name: "Medio local simulado" }).check();
  await expect(page.getByText(/Sebasanálisis no los guarda/)).toBeVisible();
  await expect(pagar).toBeDisabled();
  await page.getByLabel("Nombre").fill("Ana");
  await expect(pagar).toBeEnabled();
  await pagar.click();

  await expect(page.getByRole("heading", { name: "Pasarela simulada" })).toBeVisible();
  await expect(page.getByText("Medio: fakelocal")).toBeVisible();
  // Una recarga no vuelve a abrir la página de pago ni crea otro pago.
  await page.reload();
  await expect(page.getByText("Este enlace de pago ya se usó o venció")).toBeVisible();
  await page.getByRole("link", { name: "Volver a los planes" }).click();
  await expect(page).toHaveURL(/\/planes/);
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
  await expect(page.getByTestId("total-a-pagar")).toHaveText("32 EUR");
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
  await expect(mensual.getByText("32 EUR", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /Suscribirme|Pagar|Elegir plan/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Suscribirme|Pagar|Elegir plan/ })).toHaveCount(0);
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
  await expect(page.getByTestId("total-a-pagar")).toHaveText("32 EUR");

  await page.getByRole("radio", { name: "Renovación automática" }).check();
  await expect(page.getByText(/Antes de cada cobro te avisamos por correo/)).toBeVisible();
  const guardar = page.getByRole("button", { name: "Guardar medio de pago y pagar 32 EUR" });
  await expect(page.getByText(/solo la referencia que entrega la pasarela/)).toBeVisible();
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
  await expect(suscripcion.getByText(/32 EUR, a partir del/)).toBeVisible();

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
