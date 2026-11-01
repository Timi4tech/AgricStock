"use client"
export const API_URL =process.env.NEXT_PUBLIC_API_URL
export type User = { id: number; name: string; email: string; business_name: string; business_type: string; created_at: string };
export type AuthResponse = { access_token: string; token_type: string; user: User };
export type Item = { id: number; name: string; category: string; unit: string; quantity: string | number; unit_cost: string | number; reorder_level: string | number; notes?: string | null; created_at: string };
export type Movement = { id: number; item_id: number; item_name: string; unit: string; movement_type: string; quantity: string | number; balance_after: string | number; reason?: string | null; reference?: string | null; created_at: string };
export type Dashboard = { item_count: number; low_stock_count: number; total_stock_value: string | number; recent_movements: Movement[] };
export function getToken(): string | null { if (typeof window === "undefined") return null; return window.localStorage.getItem("agrostock_access_token"); }
export function saveSession(auth: AuthResponse) { window.localStorage.setItem("agrostock_access_token", auth.access_token); window.localStorage.setItem("agrostock_user", JSON.stringify(auth.user)); }
export function logout() { if (typeof window !== "undefined") { window.localStorage.removeItem("agrostock_access_token"); window.localStorage.removeItem("agrostock_user"); } }


async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers || {});
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  // Correlates browser requests with server-side request metadata in Upstash.
  if (!headers.has("X-Request-ID")) {
    const requestId = typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    headers.set("X-Request-ID", requestId);
  }
  const response = await fetch(`${API_URL}${path}`, { ...init, headers, cache: "no-store" });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { const body = await response.json(); message = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? body.detail.map((x: { msg?: string; loc?: string[] }) => `${x.loc?.slice(-1)[0] || "Input"}: ${x.msg || "Invalid value"}`).join("; ") : message; } catch { /* ignore non-JSON response */ }
    if (response.status === 401 && typeof window !== "undefined" && !["/api/auth/login", "/api/auth/signup"].includes(path)) { logout(); window.location.href = "/login"; }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
function idempotencyKey(): string { return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`; }
export const api = {
  getToken, saveSession, logout,
  signup: (data: Record<string, unknown>) => request<AuthResponse>("/api/auth/signup", { method: "POST", body: JSON.stringify(data) }),
  login: (data: Record<string, unknown>) => request<AuthResponse>("/api/auth/login", { method: "POST", body: JSON.stringify(data) }),
  me: () => request<User>("/api/auth/me"),
  dashboard: () => request<Dashboard>("/api/dashboard"),
  items: () => request<Item[]>("/api/items"),
  createItem: (data: Record<string, unknown>) => request<Item>("/api/items", { method: "POST", headers: { "Idempotency-Key": idempotencyKey() }, body: JSON.stringify(data) }),
  movements: () => request<Movement[]>("/api/movements?limit=100"),
  createMovement: (data: Record<string, unknown>) => request<Movement>("/api/movements", { method: "POST", headers: { "Idempotency-Key": idempotencyKey() }, body: JSON.stringify(data) }),
};
export const money = (value: string | number) => new Intl.NumberFormat("en-NG", { style: "currency", currency: "NGN", maximumFractionDigits: 2 }).format(Number(value || 0));
export const number = (value: string | number) => new Intl.NumberFormat("en-NG", { maximumFractionDigits: 3 }).format(Number(value || 0));
