import type {
  AppLogPayload,
  DatabaseEntry,
  Execution,
  Project,
  RuntimeEvent,
  Sample,
  SettingsPayload,
  SSHDiagnosticStep,
  SSHSettings,
  SSHStatus,
  ToolSummary,
} from "./detection_workspace_types";

export function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8765";
}

export async function readJsonOrThrow(resp: Response): Promise<any> {
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = typeof payload?.detail === "string" ? payload.detail : "";
    throw new Error(detail || `HTTP ${resp.status}`);
  }
  return payload;
}

export function safeText(value: unknown, fallback = ""): string {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed || fallback;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value === null || value === undefined) {
    return fallback;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

export function toProject(value: unknown): Project | null {
  if (!isRecord(value)) {
    return null;
  }
  const projectId = safeText(value.project_id);
  if (!projectId) {
    return null;
  }
  return {
    project_id: projectId,
    name: safeText(value.name, "unnamed"),
    status: safeText(value.status, "unknown"),
    description: safeText(value.description),
    last_opened_at: Number(value.last_opened_at || 0),
  };
}

export function toExecution(value: unknown): Execution | null {
  if (!isRecord(value)) {
    return null;
  }
  const executionId = safeText(value.execution_id);
  if (!executionId) {
    return null;
  }
  return {
    execution_id: executionId,
    tool_id: safeText(value.tool_id, "unknown_tool"),
    sample_id: safeText(value.sample_id),
    status: safeText(value.status, "unknown"),
    created_at: Number(value.created_at || 0),
    sample_name: safeText(value.sample_name) || undefined,
    parameters: safeText(value.parameters) || undefined,
    error: safeText(value.error) || undefined,
  };
}

export function toDatabaseEntry(value: unknown): DatabaseEntry | null {
  if (!isRecord(value)) {
    return null;
  }
  const dbId = safeText(value.db_id);
  if (!dbId) {
    return null;
  }
  return {
    db_id: dbId,
    name: safeText(value.name, "unnamed db"),
    category: safeText(value.category, "unknown"),
    resolved_path: safeText(value.resolved_path),
    configured_override: safeText(value.configured_override),
    installable: Boolean(value.installable),
    status: safeText(value.status) || undefined,
    status_message: safeText(value.status_message) || undefined,
  };
}

export function toSample(value: unknown): Sample | null {
  if (!isRecord(value)) {
    return null;
  }
  const sampleId = safeText(value.sample_id);
  if (!sampleId) {
    return null;
  }
  return {
    sample_id: sampleId,
    name: safeText(value.name, sampleId),
    source: safeText(value.source) || undefined,
    metadata: isRecord(value.metadata) ? value.metadata : {},
  };
}

export function toToolSummary(value: unknown): ToolSummary | null {
  if (!isRecord(value)) {
    return null;
  }
  const id = safeText(value.id || value.tool_id);
  if (!id) {
    return null;
  }
  return {
    id,
    name: safeText(value.name, id),
    category: safeText(value.category, "unknown"),
    description: safeText(value.description),
  };
}

export function toRuntimeEvent(value: unknown): RuntimeEvent | null {
  if (!isRecord(value)) {
    return null;
  }
  const eventType = safeText(value.event_type);
  if (!eventType) {
    return null;
  }
  return {
    seq: Number(value.seq || 0),
    event_type: eventType,
    timestamp: Number(value.timestamp || 0),
    payload: isRecord(value.payload) ? value.payload : {},
  };
}

export function toAppLogPayload(value: unknown): AppLogPayload {
  if (!isRecord(value)) {
    return { path: "", lines: [] };
  }
  return {
    path: safeText(value.path),
    lines: Array.isArray(value.lines) ? value.lines.map((item) => safeText(item)).filter(Boolean) : [],
  };
}

export function prettyJson(value: unknown): string {
  if (value === null || value === undefined) {
    return "{}";
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "{}";
  }
}

export function parseSettingsPayload(value: unknown): SettingsPayload {
  if (!isRecord(value)) {
    return {};
  }
  return value as SettingsPayload;
}

export function defaultSSHSettings(): SSHSettings {
  return {
    host: "",
    port: 22,
    user: "",
    password: "",
    use_key: false,
    key_file: "",
  };
}

export function parseSSHSettings(value: unknown): SSHSettings {
  const fallback = defaultSSHSettings();
  if (!isRecord(value)) {
    return fallback;
  }
  return {
    host: safeText(value.host),
    port: Number(value.port || fallback.port),
    user: safeText(value.user),
    password: safeText(value.password),
    use_key: Boolean(value.use_key),
    key_file: safeText(value.key_file),
  };
}

export function parseSSHStatus(value: unknown): SSHStatus | null {
  if (!isRecord(value)) {
    return null;
  }
  return {
    configured: Boolean(value.configured),
    connected: Boolean(value.connected),
    host: safeText(value.host),
    port: Number(value.port || 22),
    user: safeText(value.user),
    use_key: Boolean(value.use_key),
    key_file: safeText(value.key_file),
    has_password: Boolean(value.has_password),
    message: safeText(value.message),
  };
}

export function parseSSHDiagnosticSteps(value: unknown): SSHDiagnosticStep[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const name = safeText(item.name);
      const status = safeText(item.status) as SSHDiagnosticStep["status"];
      if (!name || !status) {
        return null;
      }
      if (status !== "ok" && status !== "fail" && status !== "running") {
        return null;
      }
      return {
        name,
        status,
        message: safeText(item.message),
      };
    })
    .filter((item: SSHDiagnosticStep | null): item is SSHDiagnosticStep => !!item);
}
