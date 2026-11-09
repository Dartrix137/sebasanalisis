/**
 * Renderiza el Markdown de un documento legal (§6.2 de la Fase 4).
 *
 * `react-markdown` no interpreta HTML crudo: una etiqueta escrita en el texto
 * nunca llega a la página como elemento. No se le agrega `rehype-raw`, que es lo
 * que lo permitiría. Las imágenes se descartan: un documento legal no las
 * necesita y cargarían recursos de otro sitio en una página pública.
 *
 * `remark-gfm` agrega las tablas de Markdown (las usan las políticas de datos y
 * de cookies). Una tabla ancha se desplaza dentro de su caja: la página no.
 */

import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const COMPONENTS: Components = {
  h1: ({ children }) => (
    <h2 className="mt-8 font-display text-2xl font-semibold leading-tight text-white">
      {children}
    </h2>
  ),
  h2: ({ children }) => (
    <h2 className="mt-8 font-display text-2xl font-semibold leading-tight text-white">
      {children}
    </h2>
  ),
  h3: ({ children }) => <h3 className="mt-6 text-base font-bold text-white">{children}</h3>,
  p: ({ children }) => <p className="mt-3 leading-relaxed">{children}</p>,
  ul: ({ children }) => <ul className="mt-3 list-disc space-y-1.5 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="mt-3 list-decimal space-y-1.5 pl-5">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  strong: ({ children }) => <strong className="font-bold text-white">{children}</strong>,
  blockquote: ({ children }) => (
    <blockquote className="rounded-lg border border-gold/40 bg-gold/10 px-4 pb-3 pt-px text-white">
      {children}
    </blockquote>
  ),
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="font-bold text-gold underline-offset-2 hover:underline"
    >
      {children}
    </a>
  ),
  hr: () => <hr className="my-6 border-edge" />,
  table: ({ children }) => (
    <div className="mt-4 overflow-x-auto rounded-lg border border-edge">
      <table className="w-full min-w-[36rem] border-collapse text-left text-xs">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border-b border-edge bg-ink-sunken px-3 py-2 align-top font-bold text-white">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border-t border-edge px-3 py-2 align-top leading-relaxed">{children}</td>
  ),
  code: ({ children }) => <code className="font-mono text-white">{children}</code>,
};

export function Markdown({ children }: { children: string }) {
  return (
    <div className="break-words text-sm text-muted">
      <ReactMarkdown
        components={COMPONENTS}
        remarkPlugins={[remarkGfm]}
        disallowedElements={["img"]}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
