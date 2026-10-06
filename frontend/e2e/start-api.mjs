// Levanta la API para los tests de punta a punta: recrea la base de e2e y
// arranca uvicorn contra ella. Lo llama Playwright (playwright.config.ts).
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const backendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "backend");

// El entorno virtual del backend si existe (desarrollo local); si no, el
// `python` del PATH (CI).
const venvPython = [
  path.join(backendDir, ".venv", "Scripts", "python.exe"),
  path.join(backendDir, ".venv", "bin", "python"),
].find(existsSync);
const python = venvPython ?? "python";

const env = {
  ...process.env,
  // La base de desarrollo local por defecto; el CI pasa la suya. El nombre
  // termina en _e2e porque prepare_e2e_db.py la borra en cada corrida.
  DATABASE_URL:
    process.env.E2E_DATABASE_URL ??
    "postgresql+psycopg://sebas:sebas@localhost:5434/sebasanalisis_e2e",
  CORS_ORIGINS: JSON.stringify([process.env.E2E_WEB_ORIGIN]),
  JWT_SECRET_KEY: "clave-solo-para-tests-de-punta-a-punta-0123456789",
  // Los correos no se envian: quedan como archivos y los tests leen el enlace.
  EMAIL_BACKEND: "file",
  EMAIL_FILE_DIR: process.env.E2E_EMAIL_DIR,
  FRONTEND_BASE_URL: process.env.E2E_WEB_ORIGIN,
  // Todas las peticiones salen de la misma IP: el limite por IP las cortaria.
  RATE_LIMIT_ENABLED: "false",
};

// Sin correos de una corrida anterior.
rmSync(process.env.E2E_EMAIL_DIR, { recursive: true, force: true });
mkdirSync(process.env.E2E_EMAIL_DIR, { recursive: true });

const prepared = spawnSync(python, [path.join("scripts", "prepare_e2e_db.py")], {
  cwd: backendDir,
  env,
  stdio: "inherit",
});
if (prepared.status !== 0) process.exit(prepared.status ?? 1);

const api = spawn(
  python,
  ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", process.env.E2E_API_PORT],
  { cwd: backendDir, env, stdio: "inherit" },
);
api.on("exit", (code) => process.exit(code ?? 0));
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => api.kill());
