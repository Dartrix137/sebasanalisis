/**
 * Cliente tipado de la API REST.
 *
 * Los tipos de `lib/types/` se mantienen sincronizados a mano con los schemas
 * Pydantic de `backend/app/schemas/` (no hay generador automático en el MVP,
 * ver la skill `api-schema-sync`). Se completa junto con cada endpoint.
 */

import type {
  LoginRequest,
  RefreshRequest,
  RegisterRequest,
  TokenResponse,
  UserResponse,
  UUID,
} from "./types/auth";
import type {
  CreateGameRequest,
  CreateGameVariantRequest,
  GameResponse,
  GameVariantResponse,
  UpdateGameRequest,
  UpdateGameVariantRequest,
} from "./types/games";
import type {
  BankrollStrategy,
  CreateSessionRequest,
  SessionResponse,
  SessionStatus,
  SessionSummaryResponse,
  UpdateSessionRequest,
} from "./types/sessions";
import type { BetResponse, CreateBetRequest } from "./types/bets";
import type {
  BulkSpinsRequest,
  BulkSpinsResponse,
  CreateSpinRequest,
  SpinResponse,
} from "./types/spins";
import type {
  BacktestReport,
  BacktestSource,
  BankrollSuggestionResponse,
  EligibleBetResponse,
  ProgressionTableResponse,
  RecommendationRecord,
  RecommendationResponse,
} from "./types/suggestions";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    /** Lista de errores del validador de configuración, cuando el 422 la trae. */
    readonly validationErrors?: string[],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Extrae un mensaje legible del `detail` de FastAPI, que tiene tres formas. */
function parseDetail(detail: unknown): { message: string; errors?: string[] } {
  if (typeof detail === "string") return { message: detail };

  if (Array.isArray(detail)) {
    // Errores de validación de Pydantic: [{ loc, msg, type }, ...]
    const msgs = detail
      .map((d) => (typeof d === "object" && d !== null && "msg" in d ? String(d.msg) : ""))
      .filter(Boolean);
    return { message: msgs[0] ?? "Datos inválidos", errors: msgs };
  }

  if (typeof detail === "object" && detail !== null) {
    const obj = detail as { message?: string; errors?: string[] };
    return { message: obj.message ?? "Datos inválidos", errors: obj.errors };
  }

  return { message: "Error inesperado" };
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit & { token?: string },
): Promise<T> {
  const { token, headers, ...rest } = init ?? {};
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
  });

  if (!res.ok) {
    let message = `Error ${res.status}`;
    let errors: string[] | undefined;
    try {
      const parsed = parseDetail((await res.json()).detail);
      message = parsed.message;
      errors = parsed.errors;
    } catch {
      // Respuesta sin cuerpo JSON: se conserva el mensaje genérico.
    }
    throw new ApiError(res.status, message, errors);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const authApi = {
  register: (body: RegisterRequest) =>
    apiFetch<TokenResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  login: (body: LoginRequest) =>
    apiFetch<TokenResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  refresh: (body: RefreshRequest) =>
    apiFetch<TokenResponse>("/auth/refresh", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  me: (token: string) => apiFetch<UserResponse>("/auth/me", { token }),
};

export const gamesApi = {
  list: (token: string, includeInactive = false) =>
    apiFetch<GameResponse[]>(
      `/games${includeInactive ? "?include_inactive=true" : ""}`,
      { token },
    ),

  variants: (token: string, gameId: UUID) =>
    apiFetch<GameVariantResponse[]>(`/games/${gameId}/variants`, { token }),

  /**
   * Una variante por su id. La devuelve aunque esté desactivada: desactivarla
   * impide abrir sesiones nuevas, no romper las ya abiertas.
   */
  variant: (token: string, variantId: UUID) =>
    apiFetch<GameVariantResponse>(`/games/variants/${variantId}`, { token }),
};

export const sessionsApi = {
  create: (token: string, body: CreateSessionRequest) =>
    apiFetch<SessionResponse>("/sessions", {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  list: (token: string, status?: SessionStatus) =>
    apiFetch<SessionResponse[]>(`/sessions${status ? `?status=${status}` : ""}`, { token }),

  get: (token: string, sessionId: UUID) =>
    apiFetch<SessionResponse>(`/sessions/${sessionId}`, { token }),

  update: (token: string, sessionId: UUID, body: UpdateSessionRequest) =>
    apiFetch<SessionResponse>(`/sessions/${sessionId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
      token,
    }),

  close: (token: string, sessionId: UUID) =>
    apiFetch<SessionResponse>(`/sessions/${sessionId}/close`, { method: "POST", token }),

  resetStrategy: (token: string, sessionId: UUID) =>
    apiFetch<SessionResponse>(`/sessions/${sessionId}/reset-strategy`, {
      method: "POST",
      token,
    }),

  /** Resumen de la sesión: cuánto se jugó y cómo terminó la banca (§4). */
  summary: (token: string, sessionId: UUID) =>
    apiFetch<SessionSummaryResponse>(`/sessions/${sessionId}/summary`, { token }),
};

/**
 * Apuestas reales que el usuario registra. Quedan pendientes y se resuelven
 * solas al entrar el número siguiente. Registrar una apuesta no es una
 * recomendación del sistema: el motor nunca dice a qué apostar.
 */
export const betsApi = {
  list: (token: string, sessionId: UUID) =>
    apiFetch<BetResponse[]>(`/sessions/${sessionId}/bets`, { token }),

  create: (token: string, sessionId: UUID, body: CreateBetRequest) =>
    apiFetch<BetResponse>(`/sessions/${sessionId}/bets`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  /** Solo se puede cancelar una apuesta que todavía no se resolvió. */
  cancel: (token: string, sessionId: UUID, betId: UUID) =>
    apiFetch<void>(`/sessions/${sessionId}/bets/${betId}`, {
      method: "DELETE",
      token,
    }),
};

export const spinsApi = {
  list: (token: string, sessionId: UUID) =>
    apiFetch<SpinResponse[]>(`/sessions/${sessionId}/spins`, { token }),

  create: (token: string, sessionId: UUID, body: CreateSpinRequest) =>
    apiFetch<SpinResponse>(`/sessions/${sessionId}/spins`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  /**
   * Carga inicial: los números ya observados en la mesa, de una vez. El backend
   * normaliza a orden cronológico ascendente según el `order` declarado (§3.5).
   */
  createBulk: (token: string, sessionId: UUID, body: BulkSpinsRequest) =>
    apiFetch<BulkSpinsResponse>(`/sessions/${sessionId}/spins/bulk`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  /** Deshacer: el backend solo permite borrar el último giro registrado. */
  remove: (token: string, sessionId: UUID, spinId: UUID) =>
    apiFetch<void>(`/sessions/${sessionId}/spins/${spinId}`, { method: "DELETE", token }),
};

/**
 * Motor de recomendación (§2.10): qué apostar en el giro siguiente, o no
 * apostar. Es lo que la vista de ruleta muestra en grande; las estadísticas
 * pasan a ser el respaldo, dentro de la misma respuesta.
 */
export const recommendationApi = {
  /** La recomendación vigente. Se recalcula al ingresar cada número. */
  latest: (token: string, sessionId: UUID) =>
    apiFetch<RecommendationResponse>(`/sessions/${sessionId}/recommendation`, { token }),

  /** Las recomendaciones emitidas en la sesión y cómo cerró cada una. */
  history: (token: string, sessionId: UUID) =>
    apiFetch<RecommendationRecord[]>(`/sessions/${sessionId}/recommendation/history`, {
      token,
    }),
};

/**
 * Gestión de banca (§2.8). Todo lo que devuelve describe el tamaño de la
 * apuesta que exige la progresión elegida y su riesgo — nunca a qué apostar.
 */
export const bankrollApi = {
  /**
   * Monto del escalón actual. `betId` es opcional porque el motor no decide a
   * qué se apuesta: sin él no se estima el riesgo de agotar la banca.
   */
  suggestion: (
    token: string,
    sessionId: UUID,
    options: { betId?: string; strategy?: BankrollStrategy } = {},
  ) => {
    const params = new URLSearchParams();
    if (options.betId !== undefined) params.set("bet", options.betId);
    if (options.strategy !== undefined) params.set("strategy_key", options.strategy);
    const qs = params.toString() ? `?${params}` : "";
    return apiFetch<BankrollSuggestionResponse>(
      `/sessions/${sessionId}/bankroll/suggestion${qs}`,
      { token },
    );
  },

  /**
   * Apuestas compatibles con el modo de la sesión, con su probabilidad teórica.
   * El riesgo de agotar la banca se estima sobre la que el usuario elija.
   */
  eligibleBets: (token: string, sessionId: UUID, strategy?: BankrollStrategy) => {
    const qs = strategy === undefined ? "" : `?strategy_key=${strategy}`;
    return apiFetch<EligibleBetResponse[]>(
      `/sessions/${sessionId}/bankroll/eligible-bets${qs}`,
      { token },
    );
  },

  /** Tabla de progresión con los montos reales de esta sesión. */
  progression: (
    token: string,
    sessionId: UUID,
    options: { stages?: number; betId?: string; strategy?: BankrollStrategy } = {},
  ) => {
    const params = new URLSearchParams();
    if (options.stages !== undefined) params.set("stages", String(options.stages));
    if (options.betId !== undefined) params.set("bet", options.betId);
    if (options.strategy !== undefined) params.set("strategy_key", options.strategy);
    const qs = params.toString() ? `?${params}` : "";
    return apiFetch<ProgressionTableResponse>(
      `/sessions/${sessionId}/bankroll/progression${qs}`,
      { token },
    );
  },

  /**
   * Tabla de progresión ANTES de activar una estrategia (§2.8): el usuario ve
   * en pesos lo que cuesta cada escalón antes de comprometerse.
   */
  progressionPreview: (
    token: string,
    params: {
      strategy: BankrollStrategy;
      baseBet: number;
      bankroll: number;
      tableLimit?: number;
      stages?: number;
      winProbability?: number;
    },
  ) => {
    const qs = new URLSearchParams({
      strategy: params.strategy,
      base_bet: String(params.baseBet),
      bankroll: String(params.bankroll),
    });
    if (params.tableLimit !== undefined) qs.set("table_limit", String(params.tableLimit));
    if (params.stages !== undefined) qs.set("stages", String(params.stages));
    if (params.winProbability !== undefined)
      qs.set("win_probability", String(params.winProbability));
    return apiFetch<ProgressionTableResponse>(`/bankroll/progression?${qs}`, { token });
  },
};

export const adminApi = {
  /**
   * Backtest del motor (§2.10). Métrica interna: no se muestra al cliente, y es
   * lo que dice si el motor aporta información útil o sólo describe el pasado.
   */
  backtest: (
    token: string,
    options: {
      variantId?: UUID;
      source?: BacktestSource;
      limit?: number;
      spins?: number;
      threshold?: number;
      weakThreshold?: number;
    } = {},
  ) => {
    const qs = new URLSearchParams();
    if (options.variantId !== undefined) qs.set("variant_id", options.variantId);
    if (options.source !== undefined) qs.set("source", options.source);
    if (options.limit !== undefined) qs.set("limit", String(options.limit));
    if (options.spins !== undefined) qs.set("spins", String(options.spins));
    if (options.threshold !== undefined) qs.set("threshold", String(options.threshold));
    if (options.weakThreshold !== undefined) {
      qs.set("weak_threshold", String(options.weakThreshold));
    }
    const sufijo = qs.toString() ? `?${qs}` : "";
    return apiFetch<BacktestReport>(`/admin/recommendations/backtest${sufijo}`, { token });
  },

  createGame: (token: string, body: CreateGameRequest) =>
    apiFetch<GameResponse>("/admin/games", {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  updateGame: (token: string, gameId: UUID, body: UpdateGameRequest) =>
    apiFetch<GameResponse>(`/admin/games/${gameId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
      token,
    }),

  createVariant: (token: string, gameId: UUID, body: CreateGameVariantRequest) =>
    apiFetch<GameVariantResponse>(`/admin/games/${gameId}/variants`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  updateVariant: (
    token: string,
    gameId: UUID,
    variantId: UUID,
    body: UpdateGameVariantRequest,
  ) =>
    apiFetch<GameVariantResponse>(`/admin/games/${gameId}/variants/${variantId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
      token,
    }),

  listUsers: (token: string) => apiFetch<UserResponse[]>("/admin/users", { token }),

  updateUserAccess: (token: string, userId: UUID, accessType: UserResponse["access_type"]) =>
    apiFetch<UserResponse>(`/admin/users/${userId}/access`, {
      method: "PATCH",
      body: JSON.stringify({ access_type: accessType }),
      token,
    }),
};
