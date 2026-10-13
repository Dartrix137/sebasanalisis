// Los tipos de `import logo from "./logo.png"`. Tambien los declara
// `next-env.d.ts`, pero ese archivo lo genera `next dev` o `next build` y no
// esta en el repositorio: el CI corre `tsc` antes de construir, sin el.
/// <reference types="next/image-types/global" />
