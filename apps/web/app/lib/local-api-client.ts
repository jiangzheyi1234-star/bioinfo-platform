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
  timeoutMs?: number;
};

const DEFAULT_REQUEST_TIMEOUT_MS = 8_000;

export class LocalApiError extends Error {
  code: LocalApiErrorCode;
  status: number;
  detail: unknown;
  title?: string;
  requestId?: string;
  problemCode?: string;

  constructor(
    code: LocalApiErrorCode,
    message: string,
    status = 0,
    detail?: unknown,
    options?: { title?: string; requestId?: string; problemCode?: string }
  ) {
    super(message);
    this.name = "LocalApiError";
    this.code = code;
    this.status = status;
    this.detail = detail;
    this.title = options?.title;
    this.requestId = options?.requestId;
    this.problemCode = options?.problemCode;
  }
}

export function apiBase(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8765";
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
  const controller = new AbortController();
  const abortFromParent = () => controller.abort(options.signal?.reason);
  const timeoutMs = Math.max(1_000, options.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS);
  const timeout = window.setTimeout(() => controller.abort(new Error("request timed out")), timeoutMs);
  if (options.signal?.aborted) {
    abortFromParent();
  } else {
    options.signal?.addEventListener("abort", abortFromParent, { once: true });
  }
  try {
    const response = await fetch(`${apiBase()}${path}`, {
      method,
      cache: options.cache,
      signal: controller.signal,
      headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const problemDetail =
        payload?.detail && typeof payload?.detail === "object" && !Array.isArray(payload.detail)
          ? (payload.detail as Record<string, unknown>)
          : payload && typeof payload === "object" && !Array.isArray(payload)
            ? (payload as Record<string, unknown>)
            : {};
      const detail = typeof problemDetail.detail === "string" ? problemDetail.detail : payload?.detail;
      const detailMessage =
        typeof detail === "string"
          ? detail
          : typeof problemDetail.title === "string"
            ? problemDetail.title
            : `HTTP ${response.status}`;
      throw new LocalApiError("backend_http_error", detailMessage, response.status, detail, {
        title: typeof problemDetail.title === "string" ? problemDetail.title : undefined,
        requestId: typeof problemDetail.requestId === "string" ? problemDetail.requestId : undefined,
        problemCode: typeof problemDetail.code === "string" ? problemDetail.code : undefined,
      });
    }
    if (
      payload &&
      typeof payload === "object" &&
      "data" in payload &&
      payload.data &&
      typeof payload.data === "object" &&
      "data" in payload.data
    ) {
      return { ...payload, data: payload.data.data } as T;
    }
    return payload as T;
  } catch (error) {
    if (error instanceof LocalApiError) {
      throw error;
    }
    throw classifyNetworkFailure(error);
  } finally {
    window.clearTimeout(timeout);
    options.signal?.removeEventListener("abort", abortFromParent);
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
