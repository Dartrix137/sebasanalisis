import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Empaqueta el servidor con solo las dependencias que realmente usa, en vez
  // de copiar node_modules completo a la imagen. Sin esto la imagen de
  // produccion pesa cientos de MB de mas.
  output: "standalone",
};

export default nextConfig;
