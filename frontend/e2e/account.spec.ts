import { expect, test } from "@playwright/test";

import {
  checkRegisterConsents,
  expectEmail,
  linkFromEmail,
  loginViaUi,
  PASSWORD,
  registerViaApi,
  uniqueEmail,
} from "./helpers";

/**
 * Flujos de cuenta del paso 1 de la Fase 4 (§13.3): un error aquí es un cliente
 * que no puede confirmar su correo o recuperar su cuenta.
 */

test("registro → correo de verificación → cuenta verificada", async ({ page }) => {
  const email = uniqueEmail();

  await page.goto("/register");
  await page.getByLabel("Tu nombre").fill("Ana");
  await page.getByLabel("Correo electrónico").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await checkRegisterConsents(page);
  await page.getByRole("button", { name: "Crear mi cuenta" }).click();
  await expect(page).toHaveURL(/\/dashboard/);

  // La cuenta entra sin confirmar y la aplicación se lo recuerda.
  const aviso = page.getByText("Confirma tu correo.");
  await expect(aviso).toBeVisible();

  // El enlace llega por correo; abrirlo confirma la cuenta.
  await page.goto(await linkFromEmail(email, "Confirma tu correo"));
  await expect(page.getByText("Tu correo quedó confirmado")).toBeVisible();

  await page.getByRole("link", { name: "Ir al menú principal" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByRole("heading", { name: /Hola, Ana/ })).toBeVisible();
  await expect(aviso).toHaveCount(0);

  await page.goto("/cuenta");
  await expect(page.getByText("Confirmado", { exact: true })).toBeVisible();
});

test("el enlace de verificación no sirve dos veces", async ({ page, request }) => {
  const email = uniqueEmail();
  await registerViaApi(request, email);
  const enlace = await linkFromEmail(email, "Confirma tu correo");

  await page.goto(enlace);
  await expect(page.getByText("Tu correo quedó confirmado")).toBeVisible();

  await page.goto(enlace);
  await expect(page.getByText("El enlace no es válido o ya venció")).toBeVisible();
});

test("restablecer la contraseña cierra la sesión que estaba abierta", async ({
  page,
  request,
  browser,
}) => {
  const email = uniqueEmail();
  const nueva = "otra-clave-e2e-distinta-456";
  await registerViaApi(request, email);

  // Una sesión abierta en un dispositivo.
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/dashboard/);

  // Desde otro dispositivo, sin sesión, se restablece la contraseña.
  const otro = await browser.newContext();
  const pagina = await otro.newPage();
  await pagina.goto("/login");
  await pagina.getByRole("link", { name: "¿Olvidaste tu contraseña?" }).click();
  // El login tiene un campo con la misma etiqueta: sin esperar a la página
  // nueva, el correo se escribiría en el formulario que se está yendo.
  await expect(pagina.getByRole("heading", { name: "Restablecer contraseña" })).toBeVisible();
  await pagina.getByLabel("Correo electrónico").fill(email);
  await pagina.getByRole("button", { name: "Enviar enlace" }).click();
  await expect(pagina.getByRole("status")).toContainText("Si ese correo tiene una cuenta");

  await pagina.goto(await linkFromEmail(email, "Restablece tu contraseña"));
  await pagina.locator("#new-password").fill(nueva);
  await pagina.getByRole("button", { name: "Guardar contraseña" }).click();
  await expect(pagina.getByRole("status")).toContainText("Tu contraseña cambió");
  await otro.close();

  // La sesión del primer dispositivo quedó cerrada.
  await page.reload();
  await expect(page).toHaveURL(/\/login/);

  // La contraseña anterior ya no entra; la nueva sí.
  await loginViaUi(page, email, PASSWORD);
  await expect(page.getByText("Correo o contrasena incorrectos")).toBeVisible();
  await loginViaUi(page, email, nueva);
  await expect(page).toHaveURL(/\/dashboard/);
});

test("eliminar la cuenta cierra la sesión y la cuenta deja de existir", async ({
  page,
  request,
}) => {
  const email = uniqueEmail();
  await registerViaApi(request, email);
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/dashboard/);

  await page.goto("/cuenta");
  await page.getByRole("button", { name: "Eliminar mi cuenta" }).click();

  // Una contraseña equivocada no borra nada.
  await page.locator("#delete-account-password").fill("no-es-esta-clave");
  await page.getByRole("button", { name: "Eliminar definitivamente" }).click();
  await expect(page.getByText("La contraseña actual no es correcta")).toBeVisible();

  await page.locator("#delete-account-password").fill(PASSWORD);
  await page.getByRole("button", { name: "Eliminar definitivamente" }).click();
  await expect(page).toHaveURL(/\/login/);

  // La cuenta ya no existe, y al usuario le llegó el aviso.
  await loginViaUi(page, email);
  await expect(page.getByText("Correo o contrasena incorrectos")).toBeVisible();
  await expectEmail(email, "fue eliminada");
});

test("reenviar el correo de confirmación deja el botón en espera", async ({ page, request }) => {
  const email = uniqueEmail();
  await registerViaApi(request, email);
  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/dashboard/);

  // El aviso dice dónde buscar antes de pedir otro correo.
  await expect(page.getByText(/revisa la carpeta de correo no deseado/)).toBeVisible();

  await page.getByRole("button", { name: "Reenviar correo" }).click();
  await expect(page.getByText(/Te enviamos un nuevo correo de confirmación/)).toBeVisible();

  // No se puede pulsar de nuevo hasta que pase la espera.
  const enEspera = page.getByRole("button", { name: /Reenviar en \d+ s/ });
  await expect(enEspera).toBeVisible();
  await expect(enEspera).toBeDisabled();
});
