// Genera los tipos del cliente API desde el OpenAPI de FastAPI (`npm run gen:types`).
//
//   1. backend/scripts/export_openapi.py  ->  lib/api/openapi.json
//   2. openapi-typescript                 ->  lib/api/schema.d.ts
//
// Los dos archivos se commitean y no se editan a mano. El CI los vuelve a
// generar y falla si quedaron distintos (docs/PLATAFORMA_COMPLETA.md §13.2).
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const backendDir = path.resolve(frontendDir, "..", "backend");
const openapiPath = path.join(frontendDir, "lib", "api", "openapi.json");
const schemaPath = path.join(frontendDir, "lib", "api", "schema.d.ts");

// El entorno virtual del backend si existe (desarrollo local); si no, el
// `python` del PATH (CI, donde las dependencias se instalan globalmente).
const venvPython = [
  path.join(backendDir, ".venv", "Scripts", "python.exe"),
  path.join(backendDir, ".venv", "bin", "python"),
].find(existsSync);
const python = venvPython ?? "python";

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: "inherit", ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

run(python, [path.join("scripts", "export_openapi.py"), openapiPath], { cwd: backendDir });
run(
  process.execPath,
  [
    path.join(frontendDir, "node_modules", "openapi-typescript", "bin", "cli.js"),
    openapiPath,
    "-o",
    schemaPath,
  ],
  { cwd: frontendDir },
);
