import type { MetadataRoute } from "next";

import { LEGAL_DOCUMENTS, legalPath } from "@/lib/legal";
import { SITE_URL } from "@/lib/site";

/**
 * `sitemap.xml`: solo las páginas públicas. `/` no va: redirige a `/login`, y
 * un sitemap no lista redirecciones.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const paths = ["/login", "/register", "/planes", ...LEGAL_DOCUMENTS.map((d) => legalPath(d.kind))];
  return paths.map((path) => ({ url: `${SITE_URL}${path}` }));
}
