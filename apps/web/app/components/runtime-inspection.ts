import {
  LocalApiError,
  apiBase,
  requestLocalApiJson,
} from "@/app/lib/local-api-client";

export type RuntimeStatus = "unknown" | "missing" | "ready";

export type RuntimeCapabilities = {
  java?: { available?: boolean; usable?: boolean; version?: string };
  nextflow?: { available?: boolean; usable?: boolean; version?: string };
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
  miniforge?: {
    installed?: boolean;
    conda_executable?: string;
  };
};

export type RuntimeInspection = {
  preflight: PreflightPayload;
  envStatus: EnvStatusPayload;
};

export type RemoteEnvInstallRequestPayload = {
  target: "workflow_runtime" | "docker_runtime";
  profile_kind?: string;
};

export async function loadRuntimeInspection(): Promise<RuntimeInspection> {
  const [preflightData, envData] = await Promise.all([
    requestLocalApiJson("POST", "/api/v1/ssh/preflight"),
    requestLocalApiJson("GET", "/api/v1/ssh/env/status", { cache: "no-store" }),
  ]);
  const preflight = (preflightData?.item || null) as PreflightPayload | null;
  if (!preflight) {
    throw new Error("运行时检测接口未返回有效的 preflight 数据");
  }
  return {
    preflight,
    envStatus: ((envData?.item || {}) as EnvStatusPayload) || {},
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

export function isRuntimeReady(preflight: PreflightPayload | null, envStatus: EnvStatusPayload | null): boolean {
  const runtimeCapabilities = preflight?.runtime_capabilities || {};
  const javaAvailable = runtimeCapabilities?.java?.usable === true;
  const nextflowAvailable = runtimeCapabilities?.nextflow?.usable === true;
  const dockerAvailable = runtimeCapabilities?.docker?.usable === true;
  const podmanAvailable = runtimeCapabilities?.podman?.usable === true;
  const micromambaAvailable = runtimeCapabilities?.micromamba?.usable === true;
  const condaAvailable = runtimeCapabilities?.conda?.usable === true || envStatus?.miniforge?.installed === true;
  return Boolean(javaAvailable && nextflowAvailable && (dockerAvailable || podmanAvailable || micromambaAvailable || condaAvailable));
}

export function deriveRuntimeStatus(inspection: RuntimeInspection | null): RuntimeStatus {
  if (!inspection) {
    return "unknown";
  }
  return isRuntimeReady(inspection.preflight, inspection.envStatus) ? "ready" : "missing";
}

export function getRecommendedDecision(preflight: PreflightPayload | null): "use_docker" | "use_podman" | "fallback_conda" {
  const runtime = preflight?.runtime_capabilities || {};
  if (preflight?.recommended_profile === "personal_docker" && runtime?.docker?.usable === true) {
    return "use_docker";
  }
  if (preflight?.recommended_profile === "personal_podman" && runtime?.podman?.usable === true) {
    return "use_podman";
  }
  return "fallback_conda";
}
