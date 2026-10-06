---
name: api-schema-sync
description: Regenera los tipos TypeScript del cliente API del frontend (frontend/lib/api/schema.d.ts) desde el OpenAPI de FastAPI con `npm run gen:types`, en Sebasanálisis. Úsala SIEMPRE que se cree, modifique o elimine un campo, enum, modelo Pydantic en backend/app/schemas/, o un endpoint (ruta, parámetros, response_model) en backend/app/api/. Los archivos generados se commitean en el mismo commit que el cambio y no se editan a mano; el CI falla si quedaron desactualizados.
---

# Tipos del cliente API: se generan, no se escriben

Los tipos TypeScript del cliente API salen del OpenAPI de FastAPI. No se mantienen a mano (decidido el 2026-10-05, `docs/PLATAFORMA_COMPLETA.md` §13.2).

## Qué hacer al cambiar un schema o un endpoint

1. Haz el cambio en `backend/app/schemas/` o `backend/app/api/`.
2. Desde `frontend/`: `npm run gen:types`.
3. `npm run typecheck`. Los errores que aparezcan son los lugares del frontend que el cambio rompió: corrígelos.
4. Commitea **en el mismo commit** el cambio del backend, `frontend/lib/api/openapi.json` y `frontend/lib/api/schema.d.ts`.

`npm run gen:types` corre `backend/scripts/export_openapi.py` (importa la app, no levanta el servidor ni toca la base) y después `openapi-typescript`. Usa el Python de `backend/.venv` si existe; si no, el `python` del PATH.

## Reglas

- **`openapi.json` y `schema.d.ts` no se editan a mano.** Si un tipo sale mal, se corrige el schema Pydantic y se regenera.
- **El CI regenera y compara** (`git diff --exit-code` sobre los dos archivos). Si cambiaste un schema y no regeneraste, falla.
- **Todo schema hereda de `ApiModel`** (`backend/app/schemas/base.py`), no de `BaseModel`. Es lo que hace que un campo de respuesta `X | None = None` se genere como `campo: X | null` y no como `campo?: X | null`: la API siempre lo envía. En las peticiones, un campo con valor por defecto sigue saliendo opcional, que es lo correcto.
- **Todo endpoint declara su `response_model`** (o su tipo de retorno). Sin él aparece en el OpenAPI sin forma y el frontend tendría que tiparlo a mano.
- **Los enums se declaran como `Enum` o `Literal`** en Pydantic, para que lleguen como uniones de literales y no como `string`.

## `frontend/lib/types/`

Cada archivo reexporta los tipos generados con el nombre que usan los componentes:

```ts
import type { components } from "../api/schema";
type S = components["schemas"];
export type SessionResponse = S["SessionResponse"];
```

- **Schema nuevo que el frontend va a usar** → agrega su línea de reexport en el archivo que corresponde al módulo de `schemas/`.
- **Schema eliminado o renombrado** → el typecheck marca el reexport roto; quítalo o renómbralo.
- **Sufijos `-Input` / `-Output`**: cuando un mismo modelo se usa en una petición y en una respuesta y sus formas difieren (un campo con valor por defecto es opcional al entrar y obligatorio al salir), FastAPI lo publica dos veces. Hoy pasa con `GameVariantConfig`, `GameCategory` y `CategoryGroup`; `lib/types/games.ts` reexporta la versión `-Output`. Si un modelo nuevo empieza a salir con sufijo, el reexport debe elegir uno explícitamente.
- Solo se escribe a mano lo que **no está en el OpenAPI**: `UUID` (alias de `string`) y `ConfigValidationError` (el `detail` de un 422).

## Lo que el generador no cubre

`apiFetch` castea la respuesta (`as T`) y **no valida en runtime**. Los tipos generados evitan que el código del frontend se desincronice del backend del mismo commit, pero un backend desplegado con una versión distinta a la del frontend todavía puede romper una pantalla. Por eso los dos salen del mismo repositorio y del mismo commit (`docs/DESPLIEGUE.md`).
