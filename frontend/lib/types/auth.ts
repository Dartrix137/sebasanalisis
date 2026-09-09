/**
 * Espejo manual de `backend/app/schemas/auth.py`.
 * Si cambia el schema Pydantic, este archivo cambia en el mismo commit
 * (ver skill `api-schema-sync` — no hay generador automático en el MVP).
 */

export type UUID = string;

export type AccessType = "trial" | "invited" | "full";
export type UserRole = "user" | "admin";

export interface RegisterRequest {
  email: string;
  password: string;
  display_name?: string | null;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RefreshRequest {
  refresh_token: string;
}

export interface UserResponse {
  id: UUID;
  email: string;
  display_name: string | null;
  access_type: AccessType;
  role: UserRole;
  created_at: string; // ISO 8601
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: UserResponse;
}
