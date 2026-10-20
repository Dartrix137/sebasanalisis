/**
 * Datos públicos del sitio: la URL que va en `robots.txt`, en `sitemap.xml` y
 * en los metadatos, y qué rutas son privadas.
 *
 * La URL va fija y no por variable de entorno (decidido el 2026-10-20): hay un
 * solo dominio, y así no hace falta un argumento de build más en Dokploy. En
 * local y en los tests apunta igual al dominio público; solo la leen los
 * buscadores.
 */

import type { Metadata } from "next";

export const SITE_URL = "https://sebasanalisis.com";

/**
 * Lo que se le suma al título de cada pantalla. Un layout que pone su título
 * como texto corta la plantilla para las carpetas de adentro: el que tenga
 * carpetas con título propio (admin, juegos, planes) la repite con
 * `sectionTitle`.
 */
export const TITLE_TEMPLATE = "%s · Sebasanálisis";

/** El título de un layout con carpetas adentro: el suyo y la plantilla para ellas. */
export function sectionTitle(title: string, template = TITLE_TEMPLATE): Metadata["title"] {
  return { default: title, template };
}

/**
 * Rutas que un buscador no debe recorrer: piden sesión, o son pasos de un
 * correo (confirmar, restablecer) que no sirven fuera de él. Cada una lleva
 * además `noindex` en sus metadatos, porque `robots.txt` no impide que se
 * indexe una URL enlazada desde otro sitio.
 */
export const PRIVATE_PATHS = [
  "/admin",
  "/cuenta",
  "/dashboard",
  "/juegos",
  "/games",
  "/pago/",
  "/planes/pagar",
  "/olvide-contrasena",
  "/restablecer-contrasena",
  "/verificar-correo",
] as const;

/** Metadatos de una pantalla privada: su título y que no se indexe. */
export function privateMetadata(title: string): Metadata {
  return { title, robots: { index: false, follow: false } };
}
