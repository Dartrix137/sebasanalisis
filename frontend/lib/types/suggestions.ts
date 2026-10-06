/**
 * Tipos de `backend/app/schemas/suggestions.py`, reexportados desde los generados.
 *
 * No se escriben a mano: salen de `lib/api/schema.d.ts`, que genera
 * `npm run gen:types` desde el OpenAPI de la API. Si cambia un schema Pydantic,
 * se regenera y se commitea en el mismo commit (skill `api-schema-sync`).
 * Aquí solo se les da el nombre que usan los componentes.
 */

import type { components } from "../api/schema";

type S = components["schemas"];

// Sugerencias estadísticas y gestión de banca (§2.6, §2.8)
export type SignalStrength = S["SignalStrength"];
export type StatisticalSuggestionItem = S["StatisticalSuggestionItem"];
export type StatisticalSuggestionsPanel = S["StatisticalSuggestionsPanel"];
export type StreakAlert = S["StreakAlert"];
export type BankrollAlertLevel = S["BankrollAlertLevel"];
export type BankrollAlertResponse = S["BankrollAlertResponse"];
export type NextStepResponse = S["NextStepResponse"];
export type BankrollSuggestionResponse = S["BankrollSuggestionResponse"];
export type EligibleBetResponse = S["EligibleBetResponse"];
export type ProgressionRowResponse = S["ProgressionRowResponse"];
export type ProgressionTableResponse = S["ProgressionTableResponse"];

// Motor de recomendación (§2.10)
export type RecommendationDecision = S["RecommendationDecision"];
export type NoBetReason = S["NoBetReason"];
export type SignalBand = S["SignalBand"];
export type RecommendationOutcome = S["RecommendationOutcome"];
export type WindowStatResponse = S["WindowStatResponse"];
export type ScoreComponentsResponse = S["ScoreComponentsResponse"];
export type MarketResponse = S["MarketResponse"];
export type ScoredMarketResponse = S["ScoredMarketResponse"];
export type MarketStakeResponse = S["MarketStakeResponse"];
export type RecommendationResponse = S["RecommendationResponse"];
export type RecommendationRecord = S["RecommendationRecord"];

// Métricas internas del motor (solo admin)
export type BacktestSource = S["BacktestSource"];
export type BacktestTally = S["BacktestTally"];
export type BacktestBandRow = S["BacktestBandRow"];
export type BacktestReport = S["BacktestReport"];
