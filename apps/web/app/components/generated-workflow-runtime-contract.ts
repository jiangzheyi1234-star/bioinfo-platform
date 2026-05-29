import type {
  GeneratedWorkflowStepRuntime,
  GeneratedWorkflowValidationIssue,
} from "./generated-workflow-model";

const RUNTIME_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

export function normalizeStepRuntime(runtime: GeneratedWorkflowStepRuntime | undefined) {
  const normalized: GeneratedWorkflowStepRuntime = {};
  if (runtime?.threads && Number.isInteger(runtime.threads) && runtime.threads > 0) {
    normalized.threads = runtime.threads;
  }
  const resources = normalizeRuntimeResources(runtime?.resources || runtime?.schedulerResources);
  if (Object.keys(resources).length > 0) {
    normalized.resources = resources;
  }
  const log = normalizeRuntimeLog(runtime?.log);
  if (log) {
    normalized.log = log;
  }
  return normalized;
}

export function validateStepRuntime(
  stepId: string,
  runtime: GeneratedWorkflowStepRuntime | undefined
): GeneratedWorkflowValidationIssue[] {
  const issues: GeneratedWorkflowValidationIssue[] = [];
  if (runtime?.threads !== undefined && (!Number.isInteger(runtime.threads) || runtime.threads < 1)) {
    issues.push({ code: "WORKFLOW_STEP_THREADS_INVALID", message: `步骤 ${stepId} 的线程数无效`, stepId });
  }
  const resources = runtime?.resources || runtime?.schedulerResources;
  if (resources) {
    for (const [name, value] of Object.entries(resources)) {
      if (!RUNTIME_NAME_RE.test(name) || !validRuntimeScalar(value)) {
        issues.push({ code: "WORKFLOW_STEP_RESOURCES_INVALID", message: `步骤 ${stepId} 的调度资源 ${name || "(empty)"} 无效`, stepId });
      }
    }
  }
  const log = runtime?.log;
  if (typeof log === "string" && log && !validRelativeRuntimePath(log)) {
    issues.push({ code: "WORKFLOW_STEP_LOG_INVALID", message: `步骤 ${stepId} 的日志路径无效`, stepId });
  } else if (log && typeof log === "object" && !Array.isArray(log)) {
    for (const [name, path] of Object.entries(log)) {
      if (!RUNTIME_NAME_RE.test(name) || !validRelativeRuntimePath(path)) {
        issues.push({ code: "WORKFLOW_STEP_LOG_INVALID", message: `步骤 ${stepId} 的日志 ${name || "(empty)"} 无效`, stepId });
      }
    }
  } else if (log !== undefined && log !== "" && log !== null) {
    issues.push({ code: "WORKFLOW_STEP_LOG_INVALID", message: `步骤 ${stepId} 的日志配置无效`, stepId });
  }
  return issues;
}

function normalizeRuntimeResources(resources: GeneratedWorkflowStepRuntime["resources"] | undefined) {
  if (!resources) return {};
  return Object.fromEntries(
    Object.entries(resources)
      .map(([name, value]) => [name.trim(), value] as const)
      .filter(([name, value]) => Boolean(name) && validRuntimeScalar(value))
  );
}

function normalizeRuntimeLog(log: GeneratedWorkflowStepRuntime["log"] | undefined) {
  if (typeof log === "string") return log.trim();
  if (!log) return "";
  const entries = Object.entries(log)
    .map(([name, path]) => [name.trim(), path.trim()] as const)
    .filter(([name, path]) => Boolean(name) && Boolean(path));
  return entries.length > 0 ? Object.fromEntries(entries) : "";
}

function validRuntimeScalar(value: unknown): value is string | number {
  return (typeof value === "string" || typeof value === "number") && value !== "";
}

function validRelativeRuntimePath(path: string) {
  const parts = path.trim().replace(/\\/g, "/").split("/");
  return Boolean(path.trim()) && !path.startsWith("/") && !/^[A-Za-z]:/.test(path) && parts.every((part) => part && part !== "." && part !== "..");
}
