import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// Next 16 retiro `next lint`: el script `lint` llama a eslint directamente.
export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // Reglas nuevas de eslint-plugin-react-hooks 6 que marcan codigo anterior a
    // la actualizacion (lib/session.tsx y los formularios de mesa y de admin).
    // Quedan como advertencia: corregirlas es reescribir el manejo de sesion,
    // y eso no entra en la preparacion del stack.
    rules: {
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
    },
  },
  globalIgnores([".next/**", "node_modules/**", "next-env.d.ts", "lib/api/schema.d.ts", "playwright-report/**", "test-results/**"]),
]);
