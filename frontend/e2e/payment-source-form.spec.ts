import { generateKeyPairSync } from "node:crypto";

import { expect, test } from "@playwright/test";
import type { Page, Route } from "@playwright/test";
import { jwtDecrypt } from "jose";

import { API_URL, confirmEmail, loginViaUi, registerViaApi, uniqueEmail } from "./helpers";

/**
 * El formulario propio de tarjeta y Nequi (§3.16 de la Fase 4).
 *
 * La API corre con la pasarela simulada, que no tiene formulario: este test le
 * hace creer a la página que la pasarela es Wompi (`availability` y la llave de
 * cifrado se interceptan) y responde por Wompi desde aquí. El token que
 * "devuelve Wompi" es uno que la pasarela simulada acepta, así que el resto del
 * recorrido (guardar el medio, cobrar, dar acceso) es el de verdad.
 *
 * Lo que se comprueba es lo que no se puede ver a mano: que la tarjeta sale
 * cifrada hacia Wompi y que a nuestra API no llega ningún dato de la tarjeta.
 */

// El origen del sandbox de verdad: la CSP del sitio solo deja hablar con Wompi
// (lib/csp.ts). Playwright responde antes de que la petición salga a la red.
const WOMPI = "https://sandbox.wompi.co/v1";
const PUBLIC_KEY = "pub_test_e2e";

const CARD_NUMBER = "4242424242424242";
const CARD_CVC = "987";
const CARD_HOLDER = "Titular Formulario";

const { publicKey: rsaPublic, privateKey: rsaPrivate } = generateKeyPairSync("rsa", {
  modulusLength: 2048,
});
const ENCRYPTION_KEY = rsaPublic.export({ type: "spki", format: "pem" }).toString();

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization,content-type",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
};

/** Lo que "responde Wompi" en cada test. */
interface FakeWompi {
  cardStatus: number;
  cardBody: unknown;
  /** Lo que llegó a POST /tokens/cards, ya descifrado. */
  cards: Record<string, unknown>[];
  nequiStatuses: string[];
  nequiPolls: number;
  /** Cuerpos que el navegador mandó a nuestra API. */
  apiBodies: string[];
}

async function fulfillJson(route: Route, status: number, body: unknown): Promise<void> {
  await route.fulfill({
    status,
    headers: { ...CORS, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function pretendWompi(page: Page): Promise<FakeWompi> {
  const wompi: FakeWompi = {
    cardStatus: 201,
    cardBody: { status: "CREATED", data: { id: "fake-token-ok", brand: "VISA", last_four: "4242" } },
    cards: [],
    nequiStatuses: ["PENDING", "APPROVED"],
    nequiPolls: 0,
    apiBodies: [],
  };

  page.on("request", (request) => {
    if (request.url().startsWith(API_URL)) wompi.apiBodies.push(request.postData() ?? "");
  });

  await page.route(`${API_URL}/billing/availability`, (route) =>
    fulfillJson(route, 200, {
      enabled: true,
      tokenizer: "wompi_api",
      public_key: PUBLIC_KEY,
      api_base_url: WOMPI,
    }),
  );
  await page.route(`${API_URL}/billing/card-encryption-key`, (route) =>
    fulfillJson(route, 200, { encryption_key: ENCRYPTION_KEY }),
  );

  await page.route(`${WOMPI}/tokens/**`, async (route) => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: CORS });
      return;
    }
    expect(request.headers()["authorization"]).toBe(`Bearer ${PUBLIC_KEY}`);
    const path = new URL(request.url()).pathname;

    if (path === "/v1/tokens/cards") {
      const body = request.postDataJSON() as { payload: string };
      // Lo único que viaja es el JWE: ni el número ni el CVC en claro.
      expect(Object.keys(body)).toEqual(["payload"]);
      expect(body.payload).not.toContain(CARD_NUMBER);
      const { payload, protectedHeader } = await jwtDecrypt(body.payload, rsaPrivate);
      expect(protectedHeader).toEqual({ alg: "RSA-OAEP-256", enc: "A256GCM" });
      wompi.cards.push(payload);
      await fulfillJson(route, wompi.cardStatus, wompi.cardBody);
      return;
    }
    if (path === "/v1/tokens/nequi") {
      expect(request.postDataJSON()).toEqual({ phone_number: "3991111111" });
      await fulfillJson(route, 200, {
        data: { id: "fake-token-ok", status: "PENDING", phone_number: "3991111111" },
      });
      return;
    }
    if (path === "/v1/tokens/nequi/fake-token-ok") {
      const status = wompi.nequiStatuses[Math.min(wompi.nequiPolls, wompi.nequiStatuses.length - 1)];
      wompi.nequiPolls += 1;
      await fulfillJson(route, 200, { data: { id: "fake-token-ok", status } });
      return;
    }
    await fulfillJson(route, 404, { error: { type: "NOT_FOUND_ERROR" } });
  });

  return wompi;
}

async function startAutomatic(page: Page): Promise<void> {
  await page
    .getByRole("article", { name: "Acceso Mensual" })
    .getByRole("link", { name: "Suscribirme" })
    .click();
  await page.getByRole("radio", { name: "Renovación automática" }).check();
  await page.getByRole("checkbox", { name: /Acepto los términos de uso de Wompi/ }).check();
  await page.getByRole("checkbox", { name: /tratamiento de mis datos personales/ }).check();
}

async function fillCard(page: Page, number: string): Promise<void> {
  await page.getByLabel("Número de la tarjeta").fill(number);
  await page.getByLabel("Vencimiento").fill("08/30");
  await page.getByLabel("CVC").fill(CARD_CVC);
  await page.getByLabel("Nombre del titular").fill(CARD_HOLDER);
}

function expectNoCardDataReachedTheApi(wompi: FakeWompi): void {
  const sent = wompi.apiBodies.join("\n");
  expect(sent).not.toContain(CARD_NUMBER);
  expect(sent).not.toContain(CARD_HOLDER);
  expect(sent).not.toContain(`"${CARD_CVC}"`);
}

test("tarjeta: va cifrada directo a Wompi y a nuestra API solo llega el token", async ({
  page,
  request,
}) => {
  const email = uniqueEmail();
  await registerViaApi(request, email, { access: "ninguno" });
  await confirmEmail(request, email);
  const wompi = await pretendWompi(page);
  await loginViaUi(page, email);
  await startAutomatic(page);

  const pagar = page.getByRole("button", { name: "Guardar medio de pago y pagar 100.000 COP" });

  // Los campos solo admiten lo que corresponde, con el formato de una tarjeta.
  const numero = page.getByLabel("Número de la tarjeta");
  await numero.pressSequentially("4242abc-4242 4242$4242");
  await expect(numero).toHaveValue("4242 4242 4242 4242");
  await expect(page.getByText("Visa", { exact: true })).toBeVisible();
  const vencimiento = page.getByLabel("Vencimiento");
  await vencimiento.pressSequentially("99e/");
  await expect(vencimiento).toHaveValue("09/9");
  await vencimiento.fill("");
  await vencimiento.pressSequentially("13");
  await expect(vencimiento).toHaveValue("1");
  const cvc = page.getByLabel("CVC");
  await cvc.pressSequentially("9a8x7 6");
  await expect(cvc).toHaveValue("987");
  const titular = page.getByLabel("Nombre del titular");
  await titular.pressSequentially("José 4 Pérez!");
  await expect(titular).toHaveValue("José Pérez");

  // Al salir de un campo mal escrito, el campo dice qué corregir.
  await vencimiento.fill("08/2");
  await titular.click();
  await expect(page.getByText("Escribe el vencimiento como MM/AA.")).toBeVisible();

  // Un número que no pasa Luhn no sale del navegador, y no se borra lo escrito.
  await fillCard(page, "4242424242424241");
  await pagar.click();
  await expect(page.getByText("El número de la tarjeta no es válido.")).toBeVisible();
  await expect(numero).toHaveValue("4242 4242 4242 4241");
  await expect(titular).toHaveValue(CARD_HOLDER);
  expect(wompi.cards).toHaveLength(0);

  // Una tarjeta vencida tampoco.
  await numero.fill(CARD_NUMBER);
  await vencimiento.fill("08/20");
  await pagar.click();
  await expect(page.getByText("Esta tarjeta ya venció.")).toBeVisible();
  expect(wompi.cards).toHaveLength(0);

  // Wompi la rechaza: un mensaje simple, sin su respuesta, y el formulario vacío.
  wompi.cardStatus = 422;
  wompi.cardBody = {
    error: { type: "INPUT_VALIDATION_ERROR", messages: { card_holder: ["detalle-crudo-de-wompi"] } },
  };
  await fillCard(page, CARD_NUMBER);
  await pagar.click();
  await expect(page.getByText(/Wompi no aceptó los datos de la tarjeta/)).toBeVisible();
  await expect(page.getByText(/detalle-crudo-de-wompi|INPUT_VALIDATION_ERROR/)).toHaveCount(0);
  await expect(page.getByLabel("Número de la tarjeta")).toHaveValue("");
  await expect(page.getByLabel("CVC")).toHaveValue("");
  await expect(page.getByLabel("Nombre del titular")).toHaveValue("");
  await expect(page).toHaveURL(/\/planes\/pagar/);

  // Wompi la acepta: el token va a nuestra API, que guarda el medio y cobra.
  wompi.cardStatus = 201;
  wompi.cardBody = { status: "CREATED", data: { id: "fake-token-ok", brand: "VISA" } };
  await fillCard(page, "4242 4242 4242 4242");
  await pagar.click();
  await expect(page).toHaveURL(/\/pago\/[0-9a-f-]+$/);
  await expect(page.getByText("Pago aprobado")).toBeVisible();

  // Lo que recibió Wompi, descifrado: los campos y formatos de su documentación.
  expect(wompi.cards.at(-1)).toMatchObject({
    number: CARD_NUMBER,
    cvc: CARD_CVC,
    exp_month: "08",
    exp_year: "30",
    card_holder: CARD_HOLDER,
  });
  expect(wompi.apiBodies.some((b) => b.includes('"payment_source_token":"fake-token-ok"'))).toBe(
    true,
  );
  expectNoCardDataReachedTheApi(wompi);
});

test("Nequi: espera la aprobación en la app; si la rechaza, se puede volver a intentar", async ({
  page,
  request,
}) => {
  const email = uniqueEmail();
  await registerViaApi(request, email, { access: "ninguno" });
  await confirmEmail(request, email);
  const wompi = await pretendWompi(page);
  await loginViaUi(page, email);
  await startAutomatic(page);
  await page.getByRole("radio", { name: "Nequi", exact: true }).check();

  // Un celular que no es de Colombia no sale del navegador.
  await page.getByLabel("Celular de tu cuenta Nequi").fill("12345");
  await page.getByRole("button", { name: "Guardar medio de pago y pagar 100.000 COP" }).click();
  await expect(page.getByText(/diez dígitos, empezando por 3/)).toBeVisible();
  expect(wompi.nequiPolls).toBe(0);

  // El cliente rechaza la solicitud en su app.
  wompi.nequiStatuses = ["PENDING", "DECLINED"];
  await page.getByLabel("Celular de tu cuenta Nequi").fill("399-111 1111");
  await expect(page.getByLabel("Celular de tu cuenta Nequi")).toHaveValue("399 111 1111");
  await page.getByRole("button", { name: "Guardar medio de pago y pagar 100.000 COP" }).click();
  await expect(page.getByText(/Wompi envió una solicitud a tu app Nequi/)).toBeVisible();
  await expect(page.getByText(/Nequi no aprobó la solicitud/)).toBeVisible({ timeout: 15_000 });
  await expect(page).toHaveURL(/\/planes\/pagar/);

  // Vuelve a intentar y esta vez la acepta.
  wompi.nequiPolls = 0;
  wompi.nequiStatuses = ["PENDING", "APPROVED"];
  await page.getByRole("button", { name: "Volver a intentar" }).click();
  await expect(page.getByText(/Wompi envió una solicitud a tu app Nequi/)).toBeVisible();
  await expect(page).toHaveURL(/\/pago\/[0-9a-f-]+$/, { timeout: 15_000 });
  await expect(page.getByText("Pago aprobado")).toBeVisible();
  expect(
    wompi.apiBodies.some(
      (b) => b.includes('"payment_source_token":"fake-token-ok"') && b.includes('"NEQUI"'),
    ),
  ).toBe(true);
});

test("Nequi: sin aprobación en el tiempo límite, se deja de esperar", async ({ page, request }) => {
  const email = uniqueEmail();
  await registerViaApi(request, email, { access: "ninguno" });
  await confirmEmail(request, email);
  const wompi = await pretendWompi(page);
  wompi.nequiStatuses = ["PENDING"];
  await page.clock.install();
  await loginViaUi(page, email);
  await startAutomatic(page);
  await page.getByRole("radio", { name: "Nequi", exact: true }).check();
  await page.getByLabel("Celular de tu cuenta Nequi").fill("3991111111");
  await page.getByRole("button", { name: "Guardar medio de pago y pagar 100.000 COP" }).click();
  await expect(page.getByText("Esperando tu aprobación…")).toBeVisible();

  await page.clock.runFor(3 * 60_000 + 10_000);
  await expect(page.getByText(/No recibimos la aprobación de Nequi a tiempo/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Volver a intentar" })).toBeVisible();
  // Con el reloj simulado, los 3 minutos pasan de un salto: basta con que haya consultado.
  expect(wompi.nequiPolls).toBeGreaterThanOrEqual(1);
});
