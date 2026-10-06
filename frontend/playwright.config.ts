import { defineConfig, devices } from "@playwright/test";

// Tests de punta a punta (docs/PLATAFORMA_COMPLETA.md §13.3): navegador real
// contra la API y una base propia. Usan puertos distintos a los de desarrollo
// para no chocar con un `npm run dev` abierto ni tocar la base de trabajo.
const API_PORT = 8010;
const WEB_PORT = 3010;
const API_URL = `http://127.0.0.1:${API_PORT}`;
const WEB_URL = `http://localhost:${WEB_PORT}`;

process.env.E2E_API_URL = API_URL;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: WEB_URL,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "node e2e/start-api.mjs",
      url: `${API_URL}/health`,
      env: { E2E_API_PORT: String(API_PORT), E2E_WEB_ORIGIN: WEB_URL },
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      // El frontend ya construido, como en producción. NEXT_PUBLIC_* se
      // incrusta durante el build, así que la URL de la API de e2e entra ahí.
      command: `npm run build && npx next start -p ${WEB_PORT}`,
      url: WEB_URL,
      env: { NEXT_PUBLIC_API_BASE_URL: API_URL },
      reuseExistingServer: false,
      timeout: 300_000,
    },
  ],
});
