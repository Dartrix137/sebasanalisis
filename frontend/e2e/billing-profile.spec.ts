import { expect, test } from "@playwright/test";

import {
  chooseFakeCard,
  confirmEmail,
  goViaAccountMenu,
  loginViaUi,
  registerViaApi,
  uniqueEmail,
} from "./helpers";

/**
 * Datos de facturación del comprador (Fase 5, paso 5.4; §3.17 de la Fase 4,
 * "Paso 5.4", punto 8): la factura electrónica va a su nombre, así que se
 * piden antes del primer pago y se cambian en "Mi cuenta". Datos inventados.
 */

test("sin datos de facturación, el pago los pide y quedan en la cuenta", async ({
  page,
  request,
}) => {
  const email = uniqueEmail();
  await registerViaApi(request, email, { access: "ninguno", facturacion: false });
  await confirmEmail(request, email);
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/planes/);
  await page
    .getByRole("article", { name: "Acceso Mensual" })
    .getByRole("link", { name: "Suscribirme" })
    .click();

  // Hasta guardarlos, no se puede pagar.
  const form = page.getByTestId("datos-de-facturacion");
  await expect(page.getByRole("heading", { name: "Datos de tu factura" })).toBeVisible();
  await expect(page.getByText("Guarda tus datos de facturación para continuar.")).toBeVisible();
  await page.getByRole("radio", { name: "Pago manual" }).check();
  await chooseFakeCard(page);
  await expect(page.getByRole("button", { name: /Ir a pagar/ })).toBeDisabled();

  await form.getByLabel("Nombres").fill("Ana María");
  await form.getByLabel("Apellidos").fill("Gómez Peña");
  await expect(form.getByLabel("País")).toHaveValue("Co");
  await expect(form.getByLabel("Tipo de documento")).toHaveValue("13");
  await form.getByLabel("Número de documento").fill("12");
  await form.getByLabel("Departamento").selectOption({ label: "Antioquia" });
  await form.getByLabel("Municipio").selectOption({ label: "Medellín" });
  await form.getByLabel("Dirección").fill("Calle 50 # 40-20");
  await form.getByRole("button", { name: "Guardar datos de facturación" }).click();

  // El servidor dice qué campo está mal.
  await expect(form.getByText("La cédula lleva de 3 a 13 dígitos.")).toBeVisible();
  await form.getByLabel("Número de documento").fill("1.234.567");
  await form.getByRole("button", { name: "Guardar datos de facturación" }).click();

  const resumen = page.getByTestId("resumen-facturacion");
  await expect(resumen.getByText("Ana María Gómez Peña")).toBeVisible();
  await expect(resumen.getByText("Cédula de ciudadanía 1234567")).toBeVisible();
  await expect(resumen.getByText("Calle 50 # 40-20, Medellín (Antioquia), Colombia")).toBeVisible();
  await expect(page.getByRole("button", { name: /Ir a pagar/ })).toBeEnabled();

  // En la cuenta se ven y se cambian.
  await goViaAccountMenu(page, "Mi cuenta");
  const cuenta = page.locator("#facturacion");
  await expect(cuenta.getByText("Ana María Gómez Peña")).toBeVisible();
  await cuenta.getByRole("button", { name: "Cambiar" }).click();
  await cuenta.getByLabel("País").selectOption({ label: "España" });
  // Fuera de Colombia, el tipo por defecto es el documento de identificación extranjero.
  await expect(cuenta.getByLabel("Tipo de documento")).toHaveValue("42");
  await cuenta.getByLabel("Tipo de documento").selectOption({ label: "Pasaporte" });
  await cuenta.getByLabel("Número de documento").fill("pa 998877");
  await cuenta.getByLabel("Estado o región").selectOption({ label: "Comunidad de Madrid" });
  await cuenta.getByLabel("Ciudad").selectOption({ label: "Madrid" });
  await cuenta.getByLabel("Dirección").fill("Calle Mayor 1");
  await cuenta.getByRole("button", { name: "Guardar datos de facturación" }).click();
  await expect(cuenta.getByText("Datos de facturación guardados.")).toBeVisible();
  await expect(cuenta.getByText("Pasaporte PA998877")).toBeVisible();
  await expect(cuenta.getByText("Calle Mayor 1, Madrid (Comunidad de Madrid), España")).toBeVisible();
});
