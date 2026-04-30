"use client";

export type LocalApiErrorCode =
  | "backend_unreachable"
  | "backend_timeout"
  | "backend_http_error"
  | "backend_invalid_response"
  | "invalid_request";

type LocalApiRequestOptions = {
  body?: unknown;
  cache?: RequestCache;
  signal?: AbortSignal;
};

export class LocalApiError extends Error {
  code: LocalApiErrorCode;
  status: number;

  constructor(code: LocalApiErrorCode, message: string, status = 0) {
    super(message);
    this.name = "LocalApiError";
    this.code = code;
    this.status = status;
  }
}

export function apiBase(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8765";
  return raw.trim().replace(/\/+$/, "");
}

export function apiWebSocketBase(): string {
  const base = apiBase();
  if (base.startsWith("https://")) {
    return `wss://${base.slice("https://".length)}`;
  }
  if (base.startsWith("http://")) {
    return `ws://${base.slice("http://".length)}`;
  }
  return base.replace(/^http/, "ws");
}

function classifyNetworkFailure(error: unknown): LocalApiError {
  const message = error instanceof Error ? error.message.trim() : String(error || "").trim();
  if (/timed out|timeout/i.test(message)) {
    return new LocalApiError("backend_timeout", "本地 API 响应超时。");
  }
  if (/Failed to fetch|NetworkError|Load failed|connect|ECONNREFUSED|unreachable/i.test(message)) {
    return new LocalApiError("backend_unreachable", `本地 API 未启动或不可达：${apiBase()}`);
  }
  return new LocalApiError("backend_invalid_response", message || "本地 API 返回了无法解析的响应。");
}

async function requestViaBrowserFetch<T>(
  method: string,
  path: string,
  options: LocalApiRequestOptions
): Promise<T> {
  try {
    const response = await fetch(`${apiBase()}${path}`, {
      method,
      cache: options.cache,
      signal: options.signal,
      headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof payload?.detail === "string" ? payload.detail : "";
      throw new LocalApiError("backend_http_error", detail || `HTTP ${response.status}`, response.status);
    }
    return payload as T;
  } catch (error) {
    if (error instanceof LocalApiError) {
      throw error;
    }
    throw classifyNetworkFailure(error);
  }
}

export async function requestLocalApiJson<T = any>(
  method: string,
  path: string,
  options: LocalApiRequestOptions = {}
): Promise<T> {
  if (!path.startsWith("/")) {
    throw new LocalApiError("invalid_request", `local api path must start with '/': ${path}`);
  }
  return requestViaBrowserFetch<T>(method, path, options);
}
