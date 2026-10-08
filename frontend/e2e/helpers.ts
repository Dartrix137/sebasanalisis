import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const API_URL = process.env.E2E_API_URL ?? "";
export const EMAIL_DIR = process.env.E2E_EMAIL_DIR ?? "";
export const PASSWORD = "clave-de-prueba-e2e-123";

/** Cada test usa su propio usuario: no comparten estado. */
export function uniqueEmail(): string {
  return `e2e-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@ejemplo.com`;
}

/** Las credenciales del administrador que siembra `e2e/start-api.mjs`. */
export const ADMIN_EMAIL = "admin-e2e@ejemplo.com";
export const ADMIN_PASSWORD = "clave-del-admin-e2e-789";

let adminToken: string | null = null;

/** Access token del administrador sembrado. Se pide una vez por worker. */
async function adminAuth(request: APIRequestContext): Promise<{ Authorization: string }> {
  if (!adminToken) {
    const login = await request.post(`${API_URL}/auth/login`, {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    });
    expect(login.ok()).toBeTruthy();
    adminToken = ((await login.json()) as { access_token: string }).access_token;
  }
  return { Authorization: `Bearer ${adminToken}` };
}

/**
 * Le da acceso a la mesa a una cuenta, como lo hace un administrador: una
 * cuenta nueva nace sin acceso (§2 de la Fase 4).
 */
export async function grantAccess(request: APIRequestContext, email: string): Promise<void> {
  const headers = await adminAuth(request);
  const found = await request.get(`${API_URL}/admin/users`, { headers, params: { query: email } });
  expect(found.ok()).toBeTruthy();
  const { items } = (await found.json()) as { items: { id: string; email: string }[] };
  const user = items.find((u) => u.email === email);
  expect(user, `cuenta ${email}`).toBeTruthy();
  const granted = await request.patch(`${API_URL}/admin/users/${user!.id}/access`, {
    headers,
    data: { access_type: "invited", reason: "Acceso para un test de punta a punta" },
  });
  expect(granted.ok()).toBeTruthy();
}

/**
 * Registra una cuenta por la API, con los consentimientos que exige el registro
 * (§6.3), y devuelve su access token.
 *
 * Por defecto la deja lista para usar la mesa, que es lo que casi todos los
 * tests necesitan: con acceso otorgado por el administrador y con la pantalla
 * de bienvenida anotada como leída. El test que trata de una de esas dos cosas
 * pasa `access: "ninguno"` u `onboarding: "pendiente"`.
 */
export async function registerViaApi(
  request: APIRequestContext,
  email: string,
  options: { onboarding?: "leido" | "pendiente"; access?: "otorgado" | "ninguno" } = {},
): Promise<string> {
  const required = await request.get(`${API_URL}/legal/required`);
  expect(required.ok()).toBeTruthy();
  const documents = (await required.json()) as { id: string }[];

  const response = await request.post(`${API_URL}/auth/register`, {
    data: {
      email,
      password: PASSWORD,
      accepted_document_ids: documents.map((d) => d.id),
      adult_confirmed: true,
    },
  });
  expect(response.ok()).toBeTruthy();
  const token = ((await response.json()) as { access_token: string }).access_token;

  if (options.onboarding !== "pendiente") {
    const done = await request.post(`${API_URL}/auth/me/onboarding`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(done.ok()).toBeTruthy();
  }
  if (options.access !== "ninguno") await grantAccess(request, email);
  return token;
}

/** Marca las casillas de consentimiento del formulario de registro. */
export async function checkRegisterConsents(page: Page): Promise<void> {
  await page.getByRole("checkbox", { name: /Acepto los Términos y Condiciones/ }).check();
  await page
    .getByRole("checkbox", { name: /Autorizo el tratamiento de mis datos personales/ })
    .check();
  await page.getByRole("checkbox", { name: /Declaro que soy mayor de edad/ }).check();
}

export async function loginViaUi(page: Page, email: string, password = PASSWORD): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Correo electrónico").fill(email);
  await page.locator("#password").fill(password);
  await page.locator("form").getByRole("button", { name: "Entrar" }).click();
}

interface StoredEmail {
  to: string;
  subject: string;
  html: string;
  text: string;
}

/**
 * El enlace del correo más reciente enviado a `to` cuyo asunto contiene
 * `subjectPart`. La API corre con EMAIL_BACKEND=file y deja cada correo como un
 * JSON en EMAIL_DIR; el envío va en segundo plano, así que se espera a que
 * aparezca.
 */
export async function linkFromEmail(to: string, subjectPart: string): Promise<string> {
  let link = "";
  await expect
    .poll(
      async () => {
        const files = (await readdir(EMAIL_DIR)).filter((f) => f.endsWith(".json")).sort();
        for (const file of files.reverse()) {
          const email = JSON.parse(
            await readFile(path.join(EMAIL_DIR, file), "utf8"),
          ) as StoredEmail;
          if (email.to !== to || !email.subject.includes(subjectPart)) continue;
          link = email.text.match(/https?:\/\/\S+token=\S+/)?.[0] ?? "";
          return link !== "";
        }
        return false;
      },
      { message: `correo "${subjectPart}" para ${to}`, timeout: 15_000 },
    )
    .toBe(true);
  return link;
}

/** Espera a que exista un correo para `to` cuyo asunto contenga `subjectPart`. */
export async function expectEmail(to: string, subjectPart: string): Promise<void> {
  await expect
    .poll(
      async () => {
        const files = (await readdir(EMAIL_DIR)).filter((f) => f.endsWith(".json"));
        for (const file of files) {
          const email = JSON.parse(
            await readFile(path.join(EMAIL_DIR, file), "utf8"),
          ) as StoredEmail;
          if (email.to === to && email.subject.includes(subjectPart)) return true;
        }
        return false;
      },
      { message: `correo "${subjectPart}" para ${to}`, timeout: 15_000 },
    )
    .toBe(true);
}
