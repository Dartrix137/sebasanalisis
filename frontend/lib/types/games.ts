/**
 * Tipos de `backend/app/schemas/games.py`, reexportados desde los generados.
 *
 * No se escriben a mano: salen de `lib/api/schema.d.ts`, que genera
 * `npm run gen:types` desde el OpenAPI de la API. Si cambia un schema Pydantic,
 * se regenera y se commitea en el mismo commit (skill `api-schema-sync`).
 * Aquí solo se les da el nombre que usan los componentes.
 */

import type { components } from "../api/schema";

type S = components["schemas"];

export type CategoryGroup = S["CategoryGroup-Output"];
export type AllowedCombination = S["AllowedCombination"];
export type GameCategory = S["GameCategory-Output"];
export type CreateGameRequest = S["CreateGameRequest"];
export type UpdateGameRequest = S["UpdateGameRequest"];
export type CreateGameVariantRequest = S["CreateGameVariantRequest"];
export type UpdateGameVariantRequest = S["UpdateGameVariantRequest"];
export type GameVariantResponse = S["GameVariantResponse"];
export type GameResponse = S["GameResponse"];

/**
 * FastAPI publica la configuración de una variante (y sus categorías y grupos)
 * dos veces: como entrada, donde un campo con valor por defecto es opcional, y
 * como salida, donde siempre viaja. Aquí se usa la de salida, que es la que
 * llega en `GameVariantResponse` y que también sirve para enviar.
 */
export type GameVariantConfig = S["GameVariantConfig-Output"];

/**
 * Detalle de un 422 del validador de configuración del admin. No está en el
 * OpenAPI (es el `detail` de un error), así que se mantiene aquí.
 */
export interface ConfigValidationError {
  message: string;
  errors: string[];
}
