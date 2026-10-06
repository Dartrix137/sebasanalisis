/**
 * Tipos de `backend/app/schemas/spins.py`, reexportados desde los generados.
 *
 * No se escriben a mano: salen de `lib/api/schema.d.ts`, que genera
 * `npm run gen:types` desde el OpenAPI de la API. Si cambia un schema Pydantic,
 * se regenera y se commitea en el mismo commit (skill `api-schema-sync`).
 * Aquí solo se les da el nombre que usan los componentes.
 */

import type { components } from "../api/schema";

type S = components["schemas"];

export type SpinSource = S["SpinSource"];
export type CreateSpinRequest = S["CreateSpinRequest"];
export type EntryOrder = S["EntryOrder"];
export type BulkSpinsRequest = S["BulkSpinsRequest"];
export type BulkSpinsResponse = S["BulkSpinsResponse"];
export type SpinResponse = S["SpinResponse"];
