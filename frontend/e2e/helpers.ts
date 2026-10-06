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

export async function registerViaApi(request: APIRequestContext, email: string): Promise<void> {
  const response = await request.post(`${API_URL}/auth/register`, {
    data: { email, password: PASSWORD },
  });
  expect(response.ok()).toBeTruthy();
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
