/**
 * Silueta de una pantalla mientras llegan la sesión o sus datos.
 *
 * Casi todas las pantallas leen la sesión de `localStorage` y piden sus datos
 * desde el navegador, así que `loading.tsx` no cubre esa espera: sin esto la
 * pantalla queda en blanco. La silueta tiene la forma de lo que viene, para que
 * el contenido no salte al llegar.
 */

import type { ReactNode } from "react";

import { BrandMark } from "./ui";

export type SkeletonShape = "page" | "mesa" | "list";

function Bar({ className = "" }: { className?: string }) {
  return <div className={`rounded-md bg-edge motion-safe:animate-pulse ${className}`} />;
}

function Block({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-card border border-edge bg-ink-raised p-4 sm:p-5 ${className}`}>
      {children}
    </div>
  );
}

/** La barra superior de `AppHeader`, sin los datos de la cuenta. */
function HeaderSkeleton() {
  return (
    <div className="border-b border-edge bg-ink-raised">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-2 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-3">
          <BrandMark size={38} />
          <span className="text-base font-extrabold leading-tight">
            Sebas<span className="text-gold">análisis</span>
          </span>
        </div>
        <Bar className="h-9 w-20" />
      </div>
    </div>
  );
}

function PageBody() {
  return (
    <div className="mx-auto max-w-3xl space-y-5 p-4 sm:p-6">
      <Bar className="h-9 w-48" />
      <Bar className="h-4 w-64 max-w-full" />
      {[0, 1].map((i) => (
        <Block key={i} className="space-y-3">
          <Bar className="h-5 w-40" />
          <Bar className="h-4 w-full" />
          <Bar className="h-4 w-3/4" />
          <Bar className="h-10 w-full" />
        </Block>
      ))}
    </div>
  );
}

function MesaBody() {
  return (
    <div className="mx-auto grid max-w-6xl grid-cols-1 items-start gap-4 p-4 sm:gap-5 sm:p-6 lg:grid-cols-2">
      <Bar className="h-9 w-36 lg:col-span-2" />
      <Block className="space-y-3">
        <Bar className="h-5 w-28" />
        <Bar className="h-10 w-4/5" />
        <Bar className="h-4 w-full" />
        <Bar className="h-16 w-full" />
      </Block>
      <Block className="space-y-4">
        <div className="flex justify-between">
          <Bar className="h-5 w-32" />
          <Bar className="h-6 w-24" />
        </div>
        <div className="grid grid-cols-7 gap-1 sm:grid-cols-10 sm:gap-1.5">
          {Array.from({ length: 37 }, (_, i) => (
            <Bar key={i} className="h-10" />
          ))}
        </div>
      </Block>
    </div>
  );
}

function ListBody() {
  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <Bar className="h-7 w-40" />
      <Bar className="h-4 w-72 max-w-full" />
      <Block className="space-y-3">
        <Bar className="h-10 w-full" />
        <Bar className="h-10 w-full" />
      </Block>
      <Block className="space-y-3">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center justify-between gap-3 border-b border-edge pb-3 last:border-0">
            <div className="flex-1 space-y-2">
              <Bar className="h-4 w-2/3" />
              <Bar className="h-3 w-1/3" />
            </div>
            <Bar className="h-9 w-14" />
          </div>
        ))}
      </Block>
    </div>
  );
}

const BODIES: Record<SkeletonShape, () => ReactNode> = {
  page: PageBody,
  mesa: MesaBody,
  list: ListBody,
};

/**
 * Silueta dentro de una pantalla que ya dibuja su logo y su título (planes,
 * pago, documentos legales): solo el contenido que falta.
 */
export function InlineSkeleton({
  kind = "cards",
  cards = 1,
}: {
  kind?: "cards" | "text";
  /** Cuántas tarjetas; dos o más van una al lado de la otra desde tableta. */
  cards?: number;
}) {
  return (
    <div role="status" aria-label="Cargando" aria-busy="true">
      {kind === "text" ? (
        <div className="space-y-3">
          <Bar className="h-10 w-2/3" />
          <Bar className="h-4 w-40" />
          {Array.from({ length: 8 }, (_, i) => (
            <Bar key={i} className={`h-4 ${i % 3 === 2 ? "w-4/5" : "w-full"}`} />
          ))}
        </div>
      ) : (
        <div className={`grid gap-4 ${cards > 1 ? "sm:grid-cols-2" : ""}`}>
          {Array.from({ length: cards }, (_, i) => (
            <Block key={i} className="space-y-3">
              <Bar className="h-6 w-40" />
              <Bar className="h-4 w-full" />
              <Bar className="h-4 w-3/4" />
              <Bar className="h-10 w-full" />
            </Block>
          ))}
        </div>
      )}
    </div>
  );
}

export function PageSkeleton({
  shape = "page",
  header = true,
}: {
  shape?: SkeletonShape;
  /** Sin la barra superior, para las pantallas que no la llevan. */
  header?: boolean;
}) {
  const Body = BODIES[shape];
  return (
    <div role="status" aria-label="Cargando" aria-busy="true" className="flex-1">
      {header ? <HeaderSkeleton /> : null}
      <Body />
    </div>
  );
}
