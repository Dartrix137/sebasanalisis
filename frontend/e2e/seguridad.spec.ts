import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { ADMIN_EMAIL, ADMIN_PASSWORD, API_URL, loginViaUi, registerViaApi, uniqueEmail } from "./helpers";

/**
 * Revisión de seguridad del paso 9 (Fase 4): la CSP con nonce y las cabeceras
 * del frontend, y el widget contra bots en los formularios de cuenta.
 */

/** Anota cada violación de la CSP que el navegador reporte en la página. */
async function watchCsp(page: Page): Promise<() => Promise<string[]>> {
  await page.addInitScript(() => {
    const w = window as unknown as { __csp: string[] };
    w.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => {
      w.__csp.push(`${e.violatedDirective} ${e.blockedURI}`);
    });
  });
  return () => page.evaluate(() => (window as unknown as { __csp: string[] }).__csp ?? []);
}

test("cada página lleva su CSP con un nonce nuevo y las cabeceras de seguridad", async ({
  request,
}) => {
  const primera = await request.get("/login");
  const segunda = await request.get("/login");
  const csp = primera.headers()["content-security-policy"];
  expect(csp).toContain("'strict-dynamic'");
  expect(csp).toContain("frame-ancestors 'none'");
  expect(csp).toContain("https://sandbox.wompi.co");
  expect(csp).toContain("frame-src https://challenges.cloudflare.com");
  const nonce = /'nonce-([^']+)'/.exec(csp)?.[1];
  expect(nonce).toBeTruthy();
  expect(segunda.headers()["content-security-policy"]).not.toContain(nonce);
  // Next le pone el nonce a sus propios scripts.
  expect(await primera.text()).toContain(`nonce="${nonce}"`);

  const h = primera.headers();
  expect(h["strict-transport-security"]).toBe("max-age=31536000");
  expect(h["x-content-type-options"]).toBe("nosniff");
  expect(h["x-frame-options"]).toBe("DENY");
  expect(h["referrer-policy"]).toBe("strict-origin-when-cross-origin");
  expect(h["x-powered-by"]).toBeUndefined();
});

test("las pantallas corren sin violar la CSP", async ({ page, request, browser }) => {
  const violaciones = await watchCsp(page);
  for (const path of ["/login", "/register", "/planes", "/legal/terminos", "/ruta-que-no-existe"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
  }

  const email = uniqueEmail();
  const token = await registerViaApi(request, email);
  const headers = { Authorization: `Bearer ${token}` };
  const menu = (await (await request.get(`${API_URL}/games`, { headers })).json()) as {
    items: { slug: string; variants: { id: string; name: string }[] }[];
  };
  const europea = menu.items
    .find((g) => g.slug === "ruleta")!
    .variants.find((v) => v.name === "european")!;
  const { id } = (await (
    await request.post(`${API_URL}/sessions`, {
      headers,
      data: { game_variant_id: europea.id, bankroll_start: 100_000, base_bet: 1_000, table_limit: 500_000 },
    })
  ).json()) as { id: string };

  await loginViaUi(page, email);
  await expect(page).toHaveURL(/\/dashboard/);
  for (const path of ["/dashboard", "/juegos/ruleta", `/juegos/ruleta/mesa/${id}`, "/cuenta"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
  }
  await expect(page.getByRole("heading", { name: "Mi cuenta" })).toBeVisible();
  expect(await violaciones()).toEqual([]);

  const admin = await (await browser.newContext()).newPage();
  const violacionesAdmin = await watchCsp(admin);
  await loginViaUi(admin, ADMIN_EMAIL, ADMIN_PASSWORD);
  await admin.waitForURL(/\/(dashboard|admin)/);
  await admin.goto("/admin/usuarios");
  await expect(admin.getByRole("heading", { name: "Usuarios" })).toBeVisible();
  expect(await violacionesAdmin()).toEqual([]);
});

test("un script inyectado en la página no corre", async ({ page }) => {
  const violaciones = await watchCsp(page);
  await page.goto("/login");
  // Lo que dejaría un texto mal escapado: un manejador en línea, sin nonce.
  await page.evaluate(() => {
    document.body.insertAdjacentHTML(
      "beforeend",
      `<img src="/no-existe.png" onerror="window.__inyectado = true">`,
    );
  });
  await page.waitForTimeout(500);
  expect(
    await page.evaluate(() => (window as unknown as { __inyectado?: boolean }).__inyectado),
  ).toBeUndefined();
  expect((await violaciones()).some((v) => v.startsWith("script-src"))).toBe(true);
});

test.describe("con la verificación contra bots encendida", () => {
  const TOKEN = "XXXX.DUMMY.TOKEN.XXXX";

  /** Turnstile de mentira: su script se sirve desde aquí, sin salir a la red. */
  async function pretendTurnstile(page: Page): Promise<void> {
    await page.route(`${API_URL}/auth/bot-check`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { "Access-Control-Allow-Origin": "*" },
        body: JSON.stringify({ site_key: "1x00000000000000000000AA" }),
      }),
    );
    await page.route("https://challenges.cloudflare.com/turnstile/v0/api.js*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/javascript",
        body: `window.turnstile = {
          render(el, opts) {
            const b = document.createElement("button");
            b.type = "button";
            b.textContent = "Soy una persona";
            b.onclick = () => opts.callback(${JSON.stringify(TOKEN)});
            el.appendChild(b);
            window.__acciones = (window.__acciones || []).concat(opts.action);
            return "w1";
          },
          reset() { window.__resets = (window.__resets || 0) + 1; },
          remove() {},
        };`,
      }),
    );
  }

  test("el ingreso espera el token y lo manda", async ({ page, request }) => {
    const violaciones = await watchCsp(page);
    const email = uniqueEmail();
    await registerViaApi(request, email);
    await pretendTurnstile(page);

    await page.goto("/login");
    await page.getByLabel("Correo electrónico").fill(email);
    await page.locator("#password").fill("clave-de-prueba-e2e-123");
    const entrar = page.locator("form").getByRole("button", { name: "Entrar" });
    await expect(entrar).toBeDisabled();

    await page.getByRole("button", { name: "Soy una persona" }).click();
    await expect(entrar).toBeEnabled();
    const login = page.waitForRequest(`${API_URL}/auth/login`);
    await entrar.click();
    expect((await login).postDataJSON()).toMatchObject({ bot_check_token: TOKEN });
    await expect(page).toHaveURL(/\/dashboard/);
    expect(await page.evaluate(() => (window as unknown as { __acciones: string[] }).__acciones)).toEqual([
      "login",
    ]);
    // El script de Turnstile lo inserta nuestro código: la CSP lo deja correr.
    expect(await violaciones()).toEqual([]);
  });

  test("tras un intento fallido se pide un token nuevo", async ({ page }) => {
    await pretendTurnstile(page);
    await page.goto("/olvide-contrasena");
    await page.getByLabel("Correo electrónico").fill("a@b");
    await page.getByRole("button", { name: "Soy una persona" }).click();
    await page.getByRole("button", { name: "Enviar enlace" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "correo" })).toBeVisible();
    expect(await page.evaluate(() => (window as unknown as { __resets?: number }).__resets)).toBe(1);
    await expect(page.getByRole("button", { name: "Enviar enlace" })).toBeDisabled();
  });
});
