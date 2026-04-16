import {
  LocalApiError,
  apiBase,
  requestLocalApiJson,
} from "@/app/lib/local-api-client";

export type RuntimeStatus = "unknown" | "missing" | "ready";

export type RuntimeCandidate = {
  available?: boolean;
  usable?: boolean;
  version?: string;
  path?: string;
  command?: string;
  home?: string;
  message?: string;
  source?: string;
  recommended?: boolean;
  meets_minimum?: boolean;
  agent_mode_supported?: boolean;
};

export type RuntimeCapabilities = {
  java?: { available?: boolean; usable?: boolean; version?: string; path?: string; home?: string; message?: string; candidates?: RuntimeCandidate[] };
  nextflow?: { available?: boolean; usable?: boolean; version?: string; path?: string; command?: string; message?: string; candidates?: RuntimeCandidate[] };
  docker?: { available?: boolean; usable?: boolean };
  podman?: { available?: boolean; usable?: boolean };
  apptainer?: { available?: boolean; usable?: boolean };
  micromamba?: { available?: boolean; usable?: boolean };
  conda?: { available?: boolean; usable?: boolean };
};

export type PreflightPayload = {
  ok: boolean;
  checks: Array<{
    key: string;
    label: string;
    status: "ok" | "warn" | "fail";
    value: string;
    message: string;
  }>;
  failures: string[];
  warnings: string[];
  recommended_profile: string;
  recommended_profile_details?: {
    profile_id?: string;
    profile_kind?: string;
  };
  supported_profile_kinds: string[];
  runtime_capabilities?: RuntimeCapabilities;
};

export type EnvStatusPayload = {
  conda_runtime?: {
    installed?: boolean;
    conda_executable?: string;
  };
};

export type RuntimeInspection = {
  preflight: PreflightPayload;
  envStatus: EnvStatusPayload;
  resolvedRuntime: {
    host_key?: string;
    selected_profile?: string;
    resolved_at?: string;
    verification_status?: string;
    nextflow_path?: string;
    nextflow_command?: string;
    nextflow_source?: string;
    nextflow_message?: string;
    java_path?: string;
    java_home?: string;
    java_message?: string;
  };
};

export type RemoteEnvInstallRequestPayload = {
  target: "workflow_runtime" | "docker_runtime";
  profile_kind?: string;
};

export async function loadRuntimeInspection(): Promise<RuntimeInspection> {
  const [preflightData, envData, resolvedData] = await Promise.all([
    requestLocalApiJson("POST", "/api/v1/ssh/preflight"),
    requestLocalApiJson("GET", "/api/v1/ssh/env/status", { cache: "no-store" }),
    requestLocalApiJson("GET", "/api/v1/runtime/resolved", { cache: "no-store" }),
  ]);
  const preflight = (preflightData?.item || null) as PreflightPayload | null;
  if (!preflight) {
    throw new Error("运行时检测接口未返回有效的 preflight 数据");
  }
  return {
    preflight,
    envStatus: ((envData?.item || {}) as EnvStatusPayload) || {},
    resolvedRuntime: ((resolvedData?.item || {}) as RuntimeInspection["resolvedRuntime"]) || {},
  };
}

export function isApiReachabilityError(error: unknown): boolean {
  if (error instanceof LocalApiError) {
    return error.code === "backend_unreachable" || error.code === "backend_timeout";
  }
  const detail = error instanceof Error ? error.message.trim() : String(error || "").trim();
  return detail === "Failed to fetch" || /NetworkError|Load failed|fetch/i.test(detail);
}

export function formatApiFetchError(error: unknown, fallbackMessage: string): string {
  const detail = error instanceof Error ? error.message.trim() : String(error || "").trim();
  if (!detail) {
    return fallbackMessage;
  }
  if (isApiReachabilityError(error)) {
    return `本地 API 未启动或不可达：${apiBase()}`;
  }
  return detail;
}

export async function verifyLocalApiHealth(): Promise<void> {
  const payload = await requestLocalApiJson("GET", "/health", { cache: "no-store" });
  if (payload?.status !== "ok") {
    throw new Error("本地 API 健康检查未返回 ok");
  }
}

export async function startRemoteEnvInstall(payload: RemoteEnvInstallRequestPayload) {
  await verifyLocalApiHealth();
  try {
    return await requestLocalApiJson("POST", "/api/v1/ssh/env/install", { body: payload });
  } catch (error) {
    if (isApiReachabilityError(error)) {
      throw new Error(
        `本地 API 健康检查已通过，但启动 Runtime 请求时连接中断：${apiBase()}/api/v1/ssh/env/install。请重试；若持续出现，请查看本地 backend 日志。`
      );
    }
    throw error;
  }
}

export function formatRuntimeInspectionError(error: unknown): string {
  return formatApiFetchError(error, "无法获取服务器的真实检测结果。");
}

export function isRuntimeReady(preflight: PreflightPayload | null, envStatus: EnvStatusPayload | null, resolvedRuntime?: RuntimeInspection["resolvedRuntime"] | null): boolean {
  const runtimeCapabilities = preflight?.runtime_capabilities || {};
  const resolvedNextflow = String(resolvedRuntime?.nextflow_path || "").trim();
  const resolvedJava = String(resolvedRuntime?.java_path || "").trim();
  const resolvedVerified = String(resolvedRuntime?.verification_status || "").trim() === "verified";
  const javaAvailable = runtimeCapabilities?.java?.usable === true || (resolvedVerified && Boolean(resolvedJava));
  const nextflowAvailable = runtimeCapabilities?.nextflow?.usable === true || (resolvedVerified && Boolean(resolvedNextflow));
  const dockerAvailable = runtimeCapabilities?.docker?.usable === true;
  return Boolean(javaAvailable && nextflowAvailable && dockerAvailable);
}

export function deriveRuntimeStatus(inspection: RuntimeInspection | null): RuntimeStatus {
  if (!inspection) {
    return "unknown";
  }
  return isRuntimeReady(inspection.preflight, inspection.envStatus, inspection.resolvedRuntime) ? "ready" : "missing";
}

export function getRecommendedDecision(_preflight: PreflightPayload | null): "use_docker" {
  return "use_docker";
}
