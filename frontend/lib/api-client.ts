/**
 * Cliente tipado de la API REST.
 *
 * Los tipos de `lib/types/` reexportan los generados desde el OpenAPI de la API
 * (`npm run gen:types`, ver la skill `api-schema-sync`). `apiFetch` no valida
 * la respuesta en runtime: confía en que backend y frontend salen del mismo
 * commit.
 */

import type {
  AdminOverviewResponse,
  AdminPaymentDetailResponse,
  AdminPaymentListResponse,
  AdminSubscriptionDetailResponse,
  AdminSubscriptionListResponse,
  AdminUserDetailResponse,
  AdminUserListResponse,
  AuditLogListResponse,
  ForcePasswordResetRequest,
  RecordRefundRequest,
  RequeryPaymentRequest,
  SubscriptionFilter,
  UpdateSubscriptionRequest,
  UpdateUserAccessRequest,
  UpdateUserRoleRequest,
  UpdateUserStatusRequest,
} from "./types/admin";
import type {
  AccessType,
  ChangeEmailRequest,
  ChangePasswordRequest,
  DeleteAccountRequest,
  ExportResponse,
  ForgotPasswordRequest,
  LoginRequest,
  MessageResponse,
  RefreshRequest,
  RegisterRequest,
  ResetPasswordRequest,
  TokenRequest,
  TokenResponse,
  UpdateProfileRequest,
  UserResponse,
  UserRole,
  UUID,
} from "./types/auth";
import type {
  AcceptanceResponse,
  AdminCouponListResponse,
  AdminCouponResponse,
  AdminPlanListResponse,
  AdminPlanResponse,
  BillingAvailabilityResponse,
  CouponRedemptionListResponse,
  CreateCouponRequest,
  CreatePlanRequest,
  PaymentListResponse,
  PaymentMethodRequest,
  PaymentKind,
  PaymentResponse,
  PaymentStatus,
  PlanResponse,
  PriceChangeResponse,
  PriceTransferPreview,
  PriceTransferRequest,
  QuoteRequest,
  QuoteResponse,
  SubscribeRequest,
  SubscribeResponse,
  RenewalMode,
  SubscriptionResponse,
  SubscriptionStatus,
  UpdateCouponRequest,
  UpdatePlanGamesRequest,
  UpdatePlanRequest,
} from "./types/billing";
import type {
  AdminGameListResponse,
  CreateGameRequest,
  CreateGameVariantRequest,
  GameMenuResponse,
  GameModule,
  GameResponse,
  GameStatus,
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
  AcceptLegalRequest,
  AdminLegalDocumentResponse,
  ConsentResponse,
  CreateLegalDocumentRequest,
  LegalDocumentResponse,
  LegalKind,
  PendingConsentResponse,
  UpdateLegalDocumentRequest,
} from "./types/legal";
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
    /** Motivo legible por código, cuando el `detail` lo trae (`consent_required`). */
    readonly code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Extrae un mensaje legible del `detail` de FastAPI, que tiene tres formas. */
function parseDetail(detail: unknown): {
  message: string;
  errors?: string[];
  code?: string;
} {
  if (typeof detail === "string") return { message: detail };

  if (Array.isArray(detail)) {
    // Errores de validación de Pydantic: [{ loc, msg, type }, ...]
    const msgs = detail
      .map((d) => (typeof d === "object" && d !== null && "msg" in d ? String(d.msg) : ""))
      .filter(Boolean);
    return { message: msgs[0] ?? "Datos inválidos", errors: msgs };
  }

  if (typeof detail === "object" && detail !== null) {
    const obj = detail as { message?: string; errors?: string[]; code?: string };
    return { message: obj.message ?? "Datos inválidos", errors: obj.errors, code: obj.code };
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
    let code: string | undefined;
    try {
      const parsed = parseDetail((await res.json()).detail);
      message = parsed.message;
      errors = parsed.errors;
      code = parsed.code;
    } catch {
      // Respuesta sin cuerpo JSON: se conserva el mensaje genérico.
    }
    throw new ApiError(res.status, message, errors, code);
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

  updateProfile: (token: string, body: UpdateProfileRequest) =>
    apiFetch<UserResponse>("/auth/me", {
      method: "PATCH",
      body: JSON.stringify(body),
      token,
    }),

  /** Confirma un correo con el token del enlace: el de la cuenta o uno nuevo. */
  verifyEmail: (body: TokenRequest) =>
    apiFetch<MessageResponse>("/auth/verify-email", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  resendVerification: (token: string) =>
    apiFetch<MessageResponse>("/auth/resend-verification", { method: "POST", token }),

  /** Responde siempre igual, exista o no una cuenta con ese correo. */
  forgotPassword: (body: ForgotPasswordRequest) =>
    apiFetch<MessageResponse>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  resetPassword: (body: ResetPasswordRequest) =>
    apiFetch<MessageResponse>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /**
   * Devuelve tokens nuevos: los anteriores dejan de valer, junto con las demás
   * sesiones abiertas de la cuenta.
   */
  changePassword: (token: string, body: ChangePasswordRequest) =>
    apiFetch<TokenResponse>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  /** Elimina la cuenta y todos sus datos. No se puede deshacer. */
  deleteAccount: (token: string, body: DeleteAccountRequest) =>
    apiFetch<void>("/auth/me", {
      method: "DELETE",
      body: JSON.stringify(body),
      token,
    }),

  /** El cambio se aplica cuando se confirma el enlace que llega al correo nuevo. */
  changeEmail: (token: string, body: ChangeEmailRequest) =>
    apiFetch<MessageResponse>("/auth/change-email", {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  /** Anota que la cuenta leyó la pantalla de bienvenida de la mesa. */
  completeOnboarding: (token: string) =>
    apiFetch<UserResponse>("/auth/me/onboarding", { method: "POST", token }),

  /** Todos los datos de la cuenta, para descargarlos (§6.4). */
  exportData: (token: string) => apiFetch<ExportResponse>("/auth/me/export", { token }),
};

/** Documentos legales y su aceptación (§6 de la Fase 4). */
export const legalApi = {
  /** La última versión publicada de un documento. Pública. */
  current: (kind: LegalKind) => apiFetch<LegalDocumentResponse>(`/legal/${kind}`),

  /** Los documentos que el registro pide aceptar. Pública. */
  required: () => apiFetch<LegalDocumentResponse[]>("/legal/required"),

  /** Lo que la cuenta debe aceptar antes de usar la mesa. */
  pending: (token: string) => apiFetch<PendingConsentResponse>("/legal/pending", { token }),

  accept: (token: string, body: AcceptLegalRequest) =>
    apiFetch<PendingConsentResponse>("/legal/accept", {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  /** Los documentos que la cuenta aceptó. */
  consents: (token: string) => apiFetch<ConsentResponse[]>("/legal/consents", { token }),
};

export const billingApi = {
  /** Los planes que se ofrecen. Público. */
  plans: () => apiFetch<PlanResponse[]>("/plans"),

  /**
   * Cuánto se cobraría. Solo viajan el plan y el código: el monto lo calcula
   * el servidor.
   */
  quote: (token: string, body: QuoteRequest) =>
    apiFetch<QuoteResponse>("/billing/quote", {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  /** Si hay una pasarela configurada. Público. */
  availability: () => apiFetch<BillingAvailabilityResponse>("/billing/availability"),

  /**
   * Abre el pago de un período y devuelve a dónde ir a pagarlo. Solo viajan el
   * plan y el código: el monto lo calcula el servidor.
   */
  subscribe: (token: string, body: SubscribeRequest) =>
    apiFetch<SubscribeResponse>("/billing/subscriptions", {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  /**
   * Cómo va un pago. `transactionId` es el `id` que la pasarela agrega a la URL
   * de regreso; el servidor lo usa solo para saber qué reconsultar.
   */
  payment: (token: string, paymentId: UUID, transactionId?: string) =>
    apiFetch<PaymentResponse>(
      `/billing/payments/${paymentId}${
        transactionId ? `?transaction_id=${encodeURIComponent(transactionId)}` : ""
      }`,
      { token },
    ),

  /**
   * Los dos contratos del procesador de pagos que se aceptan antes de guardar
   * un medio de pago, con los tokens que viajan de vuelta al suscribirse.
   */
  acceptance: (token: string) => apiFetch<AcceptanceResponse>("/billing/acceptance", { token }),

  /** Detiene la renovación automática. Conserva el acceso hasta el fin del período. */
  cancelSubscription: (token: string) =>
    apiFetch<SubscriptionResponse>("/billing/subscription/cancel", { method: "POST", token }),

  /** Revierte la cancelación antes del vencimiento. */
  resumeSubscription: (token: string) =>
    apiFetch<SubscriptionResponse>("/billing/subscription/resume", { method: "POST", token }),

  /**
   * Guarda un medio de pago en la suscripción vigente, que queda renovándose
   * sola con él. No cobra nada: el período vigente ya está pagado.
   */
  setPaymentMethod: (token: string, body: PaymentMethodRequest) =>
    apiFetch<SubscriptionResponse>("/billing/payment-method", {
      method: "PUT",
      body: JSON.stringify(body),
      token,
    }),

  /** Pasa a pago manual: deja de guardarse el medio de pago y no se cobra más. */
  removePaymentMethod: (token: string) =>
    apiFetch<SubscriptionResponse>("/billing/payment-method", { method: "DELETE", token }),

  /** El historial de pagos de la cuenta, lo más reciente primero. */
  payments: (token: string) => apiFetch<PaymentListResponse>("/billing/payments", { token }),

  /** La suscripción de la cuenta, o null si nunca pagó una. */
  subscription: (token: string) =>
    apiFetch<SubscriptionResponse | null>("/billing/subscription", { token }),
};

export const gamesApi = {
  /**
   * El menú de juegos, en su orden, con las variantes activas y la decisión de
   * acceso de cada juego. Un administrador ve también los ocultos.
   */
  list: (token: string) => apiFetch<GameMenuResponse>("/games?limit=100", { token }),

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

  /** Todos los juegos, con todas sus variantes. Pagina y filtra en el servidor. */
  listGames: (
    token: string,
    options: { status?: GameStatus; module?: GameModule; q?: string; limit?: number; offset?: number } = {},
  ) => {
    const qs = new URLSearchParams();
    if (options.status) qs.set("status", options.status);
    if (options.module) qs.set("module", options.module);
    if (options.q) qs.set("q", options.q);
    qs.set("limit", String(options.limit ?? 100));
    if (options.offset !== undefined) qs.set("offset", String(options.offset));
    return apiFetch<AdminGameListResponse>(`/admin/games?${qs}`, { token });
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

  /** Todas las versiones de los documentos legales, borradores incluidos. */
  listLegalDocuments: (token: string) =>
    apiFetch<AdminLegalDocumentResponse[]>("/admin/legal-documents", { token }),

  createLegalDocument: (token: string, body: CreateLegalDocumentRequest) =>
    apiFetch<AdminLegalDocumentResponse>("/admin/legal-documents", {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  /** Solo un borrador: una versión publicada no se edita. */
  updateLegalDocument: (token: string, documentId: UUID, body: UpdateLegalDocumentRequest) =>
    apiFetch<AdminLegalDocumentResponse>(`/admin/legal-documents/${documentId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
      token,
    }),

  publishLegalDocument: (token: string, documentId: UUID) =>
    apiFetch<AdminLegalDocumentResponse>(`/admin/legal-documents/${documentId}/publish`, {
      method: "POST",
      token,
    }),

  /** Cuentas por página, las más recientes primero. Filtra en el servidor. */
  listUsers: (
    token: string,
    options: {
      query?: string;
      accessType?: AccessType;
      role?: UserRole;
      emailVerified?: boolean;
      isActive?: boolean;
      subscription?: SubscriptionFilter;
      limit?: number;
      offset?: number;
    } = {},
  ) => {
    const qs = new URLSearchParams();
    if (options.query) qs.set("query", options.query);
    if (options.accessType !== undefined) qs.set("access_type", options.accessType);
    if (options.role !== undefined) qs.set("role", options.role);
    if (options.emailVerified !== undefined) {
      qs.set("email_verified", String(options.emailVerified));
    }
    if (options.isActive !== undefined) qs.set("is_active", String(options.isActive));
    if (options.subscription !== undefined) qs.set("subscription", options.subscription);
    if (options.limit !== undefined) qs.set("limit", String(options.limit));
    if (options.offset !== undefined) qs.set("offset", String(options.offset));
    const sufijo = qs.toString() ? `?${qs}` : "";
    return apiFetch<AdminUserListResponse>(`/admin/users${sufijo}`, { token });
  },

  getUser: (token: string, userId: UUID) =>
    apiFetch<AdminUserDetailResponse>(`/admin/users/${userId}`, { token }),

  /** Otorga o retira el acceso manual. Pide motivo y queda en la bitácora. */
  updateUserAccess: (token: string, userId: UUID, body: UpdateUserAccessRequest) =>
    apiFetch<UserResponse>(`/admin/users/${userId}/access`, {
      method: "PATCH",
      body: JSON.stringify(body),
      token,
    }),

  /** Suspende o reactiva la cuenta. Pide motivo y queda en la bitácora. */
  updateUserStatus: (token: string, userId: UUID, body: UpdateUserStatusRequest) =>
    apiFetch<UserResponse>(`/admin/users/${userId}/status`, {
      method: "PATCH",
      body: JSON.stringify(body),
      token,
    }),

  /** Nombra administrador a una cuenta o le quita el rol. Pide motivo. */
  updateUserRole: (token: string, userId: UUID, body: UpdateUserRoleRequest) =>
    apiFetch<UserResponse>(`/admin/users/${userId}/role`, {
      method: "PATCH",
      body: JSON.stringify(body),
      token,
    }),

  /** Cierra sus sesiones, anula su contraseña y le envía el enlace. Pide motivo. */
  forcePasswordReset: (token: string, userId: UUID, body: ForcePasswordResetRequest) =>
    apiFetch<MessageResponse>(`/admin/users/${userId}/force-password-reset`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  /** Le reenvía el correo para confirmar su dirección. Queda en la bitácora. */
  resendVerification: (token: string, userId: UUID) =>
    apiFetch<MessageResponse>(`/admin/users/${userId}/resend-verification`, {
      method: "POST",
      token,
    }),

  /** Indicadores del negocio, calculados en el servidor (§4.7). */
  overview: (token: string) => apiFetch<AdminOverviewResponse>("/admin/overview", { token }),

  /** La bitácora de acciones de administradores, lo más reciente primero. */
  auditLog: (token: string, options: { limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    if (options.limit !== undefined) qs.set("limit", String(options.limit));
    if (options.offset !== undefined) qs.set("offset", String(options.offset));
    const sufijo = qs.toString() ? `?${qs}` : "";
    return apiFetch<AuditLogListResponse>(`/admin/audit-log${sufijo}`, { token });
  },

  /** Todos los planes, los desactivados también. */
  listPlans: (token: string) =>
    apiFetch<AdminPlanListResponse>("/admin/plans?limit=100", { token }),

  createPlan: (token: string, body: CreatePlanRequest) =>
    apiFetch<AdminPlanResponse>("/admin/plans", {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  /** Edita, activa o desactiva. Pide motivo y queda en la bitácora. */
  updatePlan: (token: string, planId: UUID, body: UpdatePlanRequest) =>
    apiFetch<AdminPlanResponse>(`/admin/plans/${planId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
      token,
    }),

  /**
   * Los juegos que incluye un plan. Lista vacía = todos. Quitar un juego a un
   * plan con suscripciones vigentes se rechaza (409).
   */
  updatePlanGames: (token: string, planId: UUID, body: UpdatePlanGamesRequest) =>
    apiFetch<AdminPlanResponse>(`/admin/plans/${planId}/games`, {
      method: "PUT",
      body: JSON.stringify(body),
      token,
    }),

  /** Cupones por página, los más recientes primero. Busca por código. */
  listCoupons: (
    token: string,
    options: { query?: string; active?: boolean; limit?: number; offset?: number } = {},
  ) => {
    const qs = new URLSearchParams();
    if (options.query) qs.set("query", options.query);
    if (options.active !== undefined) qs.set("active", String(options.active));
    if (options.limit !== undefined) qs.set("limit", String(options.limit));
    if (options.offset !== undefined) qs.set("offset", String(options.offset));
    const sufijo = qs.toString() ? `?${qs}` : "";
    return apiFetch<AdminCouponListResponse>(`/admin/coupons${sufijo}`, { token });
  },

  createCoupon: (token: string, body: CreateCouponRequest) =>
    apiFetch<AdminCouponResponse>("/admin/coupons", {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  /** Edita, activa o desactiva. Pide motivo y queda en la bitácora. */
  updateCoupon: (token: string, couponId: UUID, body: UpdateCouponRequest) =>
    apiFetch<AdminCouponResponse>(`/admin/coupons/${couponId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
      token,
    }),

  /** Quién usó el cupón y cuándo, lo más reciente primero. */
  couponRedemptions: (
    token: string,
    couponId: UUID,
    options: { limit?: number; offset?: number } = {},
  ) => {
    const qs = new URLSearchParams();
    if (options.limit !== undefined) qs.set("limit", String(options.limit));
    if (options.offset !== undefined) qs.set("offset", String(options.offset));
    const sufijo = qs.toString() ? `?${qs}` : "";
    return apiFetch<CouponRedemptionListResponse>(
      `/admin/coupons/${couponId}/redemptions${sufijo}`,
      { token },
    );
  },

  /** Cuántas vigentes del plan tienen otro precio, y el traslado en curso (§4.10). */
  priceTransferPreview: (token: string, planId: UUID) =>
    apiFetch<PriceTransferPreview>(`/admin/plans/${planId}/price-transfer`, { token }),

  /** Traslada el precio actual del plan a sus suscripciones vigentes. Pide motivo. */
  createPriceTransfer: (token: string, planId: UUID, body: PriceTransferRequest) =>
    apiFetch<PriceChangeResponse>(`/admin/plans/${planId}/price-transfer`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  /** Cancela lo que falta por aplicar de un traslado. Pide motivo. */
  cancelPriceTransfer: (token: string, changeId: UUID, body: PriceTransferRequest) =>
    apiFetch<PriceChangeResponse>(`/admin/price-changes/${changeId}/cancel`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  /** Suscripciones por página, las más recientes primero. Filtra en el servidor. */
  listSubscriptions: (
    token: string,
    options: {
      status?: SubscriptionStatus;
      planId?: UUID;
      renewalMode?: RenewalMode;
      query?: string;
      limit?: number;
      offset?: number;
    } = {},
  ) => {
    const qs = new URLSearchParams();
    if (options.status !== undefined) qs.set("status", options.status);
    if (options.planId !== undefined) qs.set("plan_id", options.planId);
    if (options.renewalMode !== undefined) qs.set("renewal_mode", options.renewalMode);
    if (options.query) qs.set("query", options.query);
    if (options.limit !== undefined) qs.set("limit", String(options.limit));
    if (options.offset !== undefined) qs.set("offset", String(options.offset));
    const sufijo = qs.toString() ? `?${qs}` : "";
    return apiFetch<AdminSubscriptionListResponse>(`/admin/subscriptions${sufijo}`, { token });
  },

  getSubscription: (token: string, subscriptionId: UUID) =>
    apiFetch<AdminSubscriptionDetailResponse>(`/admin/subscriptions/${subscriptionId}`, {
      token,
    }),

  /** Extender o cancelar. Pide motivo, queda en la bitácora y se le avisa al cliente. */
  updateSubscription: (token: string, subscriptionId: UUID, body: UpdateSubscriptionRequest) =>
    apiFetch<AdminSubscriptionDetailResponse>(`/admin/subscriptions/${subscriptionId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
      token,
    }),

  /** Cobros por página, los más recientes primero, también los que no se completaron. */
  listPayments: (
    token: string,
    options: {
      status?: PaymentStatus;
      kind?: PaymentKind;
      reversed?: boolean;
      refunded?: boolean;
      query?: string;
      limit?: number;
      offset?: number;
    } = {},
  ) => {
    const qs = new URLSearchParams();
    if (options.status !== undefined) qs.set("status", options.status);
    if (options.kind !== undefined) qs.set("kind", options.kind);
    if (options.reversed) qs.set("reversed", "true");
    if (options.refunded) qs.set("refunded", "true");
    if (options.query) qs.set("query", options.query);
    if (options.limit !== undefined) qs.set("limit", String(options.limit));
    if (options.offset !== undefined) qs.set("offset", String(options.offset));
    const sufijo = qs.toString() ? `?${qs}` : "";
    return apiFetch<AdminPaymentListResponse>(`/admin/payments${sufijo}`, { token });
  },

  /** El pago con sus eventos del proveedor, sus reembolsos y su bitácora. */
  getPayment: (token: string, paymentId: UUID) =>
    apiFetch<AdminPaymentDetailResponse>(`/admin/payments/${paymentId}`, { token }),

  /** Vuelve a preguntarle a Wompi. Es la misma función del webhook. */
  requeryPayment: (token: string, paymentId: UUID, body: RequeryPaymentRequest) =>
    apiFetch<AdminPaymentDetailResponse>(`/admin/payments/${paymentId}/requery`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  /** Registra un reembolso hecho en el panel de Wompi. No mueve el pago ni el acceso. */
  recordRefund: (token: string, paymentId: UUID, body: RecordRefundRequest) =>
    apiFetch<AdminPaymentDetailResponse>(`/admin/payments/${paymentId}/refunds`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),
};
