import type { Config } from "tailwindcss";

/**
 * Sistema visual inferido de los mockups en `docs/design/`:
 * fondo azul-noche muy oscuro, tarjetas elevadas con borde sutil, acento dorado
 * para la accion primaria, tipografia sans con titulos en peso alto.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "#0a1120", // fondo de pagina
          raised: "#101a2e", // tarjeta
          sunken: "#16203a", // input
        },
        edge: "#1e2a44", // borde de tarjeta / input
        gold: {
          DEFAULT: "#dda520", // acento primario (boton, marca, pestana activa)
          soft: "#f0c95a",
          ink: "#3a2b05", // texto sobre dorado
        },
        muted: "#8d9ab4", // texto secundario
        table: {
          red: "#d02434", // numero rojo de la ruleta
          black: "#1b2233", // numero negro de la ruleta
          green: "#1f9d55", // cero
        },
        signal: {
          strong: "#1f9d55",
          medium: "#dda520",
          weak: "#8d9ab4",
        },
      },
      fontFamily: {
        display: ["var(--font-display)", "Arial Narrow", "sans-serif"],
      },
      borderRadius: { card: "0.875rem" },
      boxShadow: { card: "0 1px 0 0 rgba(255,255,255,0.03) inset" },
      keyframes: {
        "chip-in": {
          from: { opacity: "0", transform: "translateX(-6px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
      },
      animation: {
        "chip-in": "chip-in 260ms ease-out both",
      },
    },
  },
  plugins: [],
};

export default config;
