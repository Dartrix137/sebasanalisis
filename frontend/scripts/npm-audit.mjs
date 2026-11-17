// Auditoria de las dependencias de produccion: `npm audit --omit=dev`, y falla
// con cualquier alerta alta o critica, salvo las de EXCEPCIONES mientras no
// venzan. Lo corren el CI y la auditoria semanal (.github/workflows).
//
// Una excepcion es para un aviso que no tiene correccion publicada y que no
// alcanza a la aplicacion en ejecucion. Lleva su motivo y una fecha de
// revision: pasada esa fecha, el aviso vuelve a hacer fallar el CI y hay que
// mirarlo otra vez. Nunca se exceptua un aviso que ya tenga correccion.

import { spawnSync } from "node:child_process";

const BLOCKING = new Set(["high", "critical"]);

/** Avisos exceptuados, por su id de GitHub (GHSA). */
const EXCEPCIONES = {
  // picomatch <=4.0.7, ReDoS con extglobs de una sola rama (alta). Sin version
  // corregida: la 4.0.7 es la ultima publicada (2026-11-17). Entra solo por
  // @sentry/nextjs -> @rollup/plugin-commonjs (tambien en la 11.14.0), que lo
  // usa unicamente `config/loaders/wrappingLoader.js`: un loader de webpack
  // que corre al compilar, con patrones fijos del proyecto. Ningun dato de un
  // usuario llega a un glob. Decidido por el usuario el 2026-11-17.
  "GHSA-fc5q-39xc-vjpf": { revisar: "2026-12-17", paquete: "picomatch" },
};

const result = spawnSync("npm", ["audit", "--omit=dev", "--json"], {
  encoding: "utf8",
  shell: process.platform === "win32",
});
let report;
try {
  report = JSON.parse(result.stdout);
} catch {
  console.error("npm audit no devolvio JSON:\n", result.stderr || result.stdout);
  process.exit(1);
}

const today = new Date().toISOString().slice(0, 10);
const ghsa = (url) => (url ?? "").match(/GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}/)?.[0];

// Los avisos de verdad: los `via` que son objetos. Un paquete que solo
// "depende de" otro vulnerable no trae aviso propio.
const advisories = new Map();
for (const [name, vuln] of Object.entries(report.vulnerabilities ?? {})) {
  for (const via of vuln.via ?? []) {
    if (typeof via !== "object") continue;
    const id = ghsa(via.url) ?? `${name}:${via.title}`;
    advisories.set(id, { id, name, severity: via.severity, title: via.title, url: via.url });
  }
}

let failed = false;
for (const advisory of [...advisories.values()].sort((a, b) => a.id.localeCompare(b.id))) {
  const line = `${advisory.severity} ${advisory.name}: ${advisory.title} (${advisory.url ?? advisory.id})`;
  if (!BLOCKING.has(advisory.severity)) {
    console.log(`  aviso      ${line}`);
    continue;
  }
  const exception = EXCEPCIONES[advisory.id];
  if (exception && exception.paquete === advisory.name && today <= exception.revisar) {
    console.log(`  exceptuado ${line} (revisar el ${exception.revisar})`);
    continue;
  }
  if (exception) {
    console.log(`  VENCIDA    ${line}: la excepcion era hasta el ${exception.revisar}`);
  } else {
    console.log(`  BLOQUEA    ${line}`);
  }
  failed = true;
}

if (advisories.size === 0) console.log("Sin alertas en las dependencias de produccion.");
process.exit(failed ? 1 : 0);
