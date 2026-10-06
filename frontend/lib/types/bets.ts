/**
 * Tipos de `backend/app/schemas/bets.py`, reexportados desde los generados.
 *
 * No se escriben a mano: salen de `lib/api/schema.d.ts`, que genera
 * `npm run gen:types` desde el OpenAPI de la API. Si cambia un schema Pydantic,
 * se regenera y se commitea en el mismo commit (skill `api-schema-sync`).
 * Aquí solo se les da el nombre que usan los componentes.
 */

import type { components } from "../api/schema";

type S = components["schemas"];

export type BetStatus = S["BetStatus"];
export type CreateBetRequest = S["CreateBetRequest"];
export type BetResponse = S["BetResponse"];
