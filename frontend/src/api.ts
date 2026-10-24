import { fetch as expoFetch } from "expo/fetch";

import { storage } from "@/src/utils/storage";

export const BASE = `${process.env.EXPO_PUBLIC_BACKEND_URL}/api`;
export const TOKEN_KEY = "auth_token";

let token: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setToken(t: string | null) {
  token = t;
}
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}
export async function clearStoredToken() {
  token = null;
  await storage.secureRemove(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: any } = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: opts.method ?? "GET",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401) {
    await clearStoredToken();
    onUnauthorized?.();
  }
  if (!res.ok) {
    let msg = `Erro ${res.status}`;
    try {
      const j = await res.json();
      msg = j.detail ?? msg;
    } catch {}
    throw new ApiError(res.status, typeof msg === "string" ? msg : "Erro");
  }
  return res.json();
}

// Server-sent events stream (AI analysis). Calls onDelta for each text chunk.
export async function streamSSE(path: string, body: any, onDelta: (t: string) => void, signal?: AbortSignal) {
  const res = await expoFetch(`${BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) throw new ApiError(res.status, "Falha na análise IA");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() ?? "";
    for (const p of parts) {
      const line = p.trim();
      if (!line.startsWith("data:")) continue;
      const data = line.slice(5).trim();
      if (data === "[DONE]") return;
      const j = JSON.parse(data);
      if (j.error) throw new Error(j.error);
      if (j.t) onDelta(j.t);
    }
  }
}

export function fmt(n: number, d = 2) {
  if (n === null || n === undefined || isNaN(n)) return "—";
  return n.toLocaleString("pt-PT", { minimumFractionDigits: d, maximumFractionDigits: d });
}
export function money(n: number) {
  return `$${fmt(n, 2)}`;
}
export function pct(n: number) {
  return `${n >= 0 ? "+" : ""}${fmt(n, 2)}%`;
}
