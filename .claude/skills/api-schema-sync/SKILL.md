---
name: api-schema-sync
description: Mantiene sincronizados los schemas Pydantic del backend (backend/app/schemas/) con los tipos TypeScript del cliente API del frontend (frontend/lib/api-client.ts y tipos asociados) en Sebasanálisis, ya que el MVP no usa un generador automático de tipos. Úsala SIEMPRE que se cree, modifique o elimine un campo, enum, o modelo Pydantic en backend/app/schemas/, y también al construir por primera vez el cliente API del frontend. Sin esta skill es fácil que el frontend quede con tipos desactualizados sin que ningún error de compilación lo detecte a tiempo.
---

# Sincronización manual de schemas — backend (Pydantic) ↔ frontend (TypeScript)

Sebasanálisis no tiene generador automático de tipos en el MVP (ver `CLAUDE.md` — decisión explícita). Esto significa que cualquier cambio en un schema Pydantic debe reflejarse a mano en el tipo TypeScript correspondiente, en el mismo cambio/commit — nunca en un paso posterior "para después".

## Mapeo de archivos (backend → frontend)

| Schema Pydantic (backend) | Tipo TypeScript (frontend) |
| ------------------------- | -------------------------- |
| `schemas/auth.py`         | `lib/types/auth.ts`        |
| `schemas/games.py`        | `lib/types/games.ts`       |
| `schemas/sessions.py`     | `lib/types/sessions.ts`    |
| `schemas/spins.py`        | `lib/types/spins.ts`       |
| `schemas/bets.py`         | `lib/types/bets.ts`        |
| `schemas/suggestions.py`  | `lib/types/suggestions.ts` |
| `schemas/screenshots.py`  | `lib/types/screenshots.ts` |

Si esta estructura de carpetas cambia en el proyecto real, actualiza esta tabla — no dejes que quede desactualizada, porque entonces la skill misma se vuelve la fuente de bugs.

## Reglas de traducción Pydantic → TypeScript

| Pydantic                                                      | TypeScript                                                                                                     |
| ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `str`                                                         | `string`                                                                                                       |
| `int` / `float`                                               | `number`                                                                                                       |
| `bool`                                                        | `boolean`                                                                                                      |
| `UUID`                                                        | `string` (con alias `type UUID = string` si se quiere semántica)                                               |
| `datetime`                                                    | `string` (ISO 8601 — el frontend parsea con `new Date()` donde haga falta)                                     |
| `Optional[X]` / `X \| None`                                   | `X \| null` (o `X?` si el campo puede estar ausente, no solo null — verificar cuál aplica)                     |
| `Enum(str, Enum)`                                             | `type X = 'valor1' \| 'valor2' \| ...` (union de string literals, no `enum` de TS — más simple de sincronizar) |
| `list[X]`                                                     | `X[]`                                                                                                          |
| `dict[str, X]`                                                | `Record<string, X>`                                                                                            |
| Modelo anidado (ej. `CategoryGroup` dentro de `GameCategory`) | Interface anidada equivalente, mismo nombre                                                                    |

## Checklist al modificar un schema Pydantic

1. ¿Agregaste, quitaste o renombraste un campo? → replica el cambio en el archivo TS correspondiente en el mismo commit.
2. ¿Cambiaste un `Enum`? → actualiza el union type de TS con los mismos valores exactos (son strings, deben coincidir carácter por carácter — el backend los serializa tal cual).
3. ¿Agregaste un modelo nuevo (ej. una nueva respuesta compuesta)? → crea la interface TS correspondiente antes de que el frontend intente consumir ese endpoint.
4. ¿El campo es opcional en Pydantic (`Optional[X] = None`)? → decide explícitamente si en TS es `X | null`, `X?`, o ambos, según si el backend puede omitir la clave del JSON o siempre la envía en `null`. Esto es una fuente común de bugs si se asume mal.

## Nota sobre schemas ya definidos en el proyecto

Los schemas iniciales (`auth.py`, `games.py`, `sessions.py`, `spins.py`, `bets.py`, `suggestions.py`, `screenshots.py`) ya fueron diseñados junto con el resto del proyecto. Al construir el cliente API del frontend por primera vez, revisa cada uno completo y genera su tipo TS correspondiente siguiendo la tabla de traducción — no empieces el cliente API sin haber cubierto los 7 archivos.

## Cuándo esta skill deja de ser necesaria

Si en una fase futura se decide introducir un generador automático de tipos (ej. `openapi-typescript` a partir del schema OpenAPI que FastAPI expone automáticamente), esta skill queda obsoleta — pero mientras el MVP no lo tenga, es la única barrera contra el drift silencioso entre backend y frontend.
