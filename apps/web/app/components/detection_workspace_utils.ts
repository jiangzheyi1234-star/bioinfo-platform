import type {
  AppLogPayload,
  DatabaseEntry,
  InstallJobSnapshot,
  MiniforgeStatus,
  PreflightCheck,
  PreflightResult,
  Project,
  RemoteEnvStatus,
  RuntimeEvent,
  Sample,
  SettingsPayload,
  SSHDiagnosticStep,
  SSHSettings,
  SSHStatus,
  Task,
  ToolEnvStatus,
  ServerDoctorReport,
  WorkflowArtifact,
  WorkflowCompilePreview,
  WorkflowResult,
  WorkflowRuntimeCapabilities,
  WorkflowServerProfile,
  WorkflowRun,
} from "./detection_workspace_types";

export function apiBase(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8765";
  return raw.trim().replace(/\/+$/, "");
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

export function toTask(value: unknown): Task | null {
  if (!isRecord(value)) {
    return null;
  }
  const taskId = safeText(value.task_id);
  if (!taskId) {
    return null;
  }
  return {
    task_id: taskId,
    project_id: safeText(value.project_id),
    title: safeText(value.title, taskId),
    description: safeText(value.description),
    status: safeText(value.status, "pending"),
    created_at: Number(value.created_at || 0),
    updated_at: Number(value.updated_at || 0),
    last_activity_at: Number(value.last_activity_at || 0),
    latest_execution_id: safeText(value.latest_execution_id),
    summary: safeText(value.summary),
    result_snapshot: isRecord(value.result_snapshot) ? value.result_snapshot : {},
    execution_count: Number(value.execution_count || 0),
    failed_execution_count: Number(value.failed_execution_count || 0),
    latest_execution_created_at: Number(value.latest_execution_created_at || 0),
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
    description: safeText(value.description),
    resolved_path: safeText(value.resolved_path),
    configured_override: safeText(value.configured_override),
    installable: Boolean(value.installable),
    install_job_id: safeText(value.install_job_id) || undefined,
    install_stage: safeText(value.install_stage) || undefined,
    status: safeText(value.status) || undefined,
    status_message: safeText(value.status_message) || undefined,
  };
}

export function toPreflightCheck(value: unknown): PreflightCheck | null {
  if (!isRecord(value)) {
    return null;
  }
  const key = safeText(value.key);
  if (!key) {
    return null;
  }
  const status = safeText(value.status) as PreflightCheck["status"];
  if (!status || !["ok", "warn", "fail"].includes(status)) {
    return null;
  }
  return {
    key,
    label: safeText(value.label, key),
    status,
    value: safeText(value.value),
    message: safeText(value.message),
  };
}

export function parsePreflightResult(value: unknown): PreflightResult | null {
  if (!isRecord(value)) {
    return null;
  }
  return {
    ok: Boolean(value.ok),
    arch: safeText(value.arch),
    free_disk_gb: Number(value.free_disk_gb || 0),
    recommended_profile: safeText(value.recommended_profile),
    recommended_profile_details: parseWorkflowServerProfile(value.recommended_profile_details),
    runtime_capabilities: parseWorkflowRuntimeCapabilities(value.runtime_capabilities),
    checks: Array.isArray(value.checks)
      ? value.checks.map(toPreflightCheck).filter((item: PreflightCheck | null): item is PreflightCheck => !!item)
      : [],
    failures: Array.isArray(value.failures) ? value.failures.map((item) => safeText(item)).filter(Boolean) : [],
    warnings: Array.isArray(value.warnings) ? value.warnings.map((item) => safeText(item)).filter(Boolean) : [],
  };
}

export function toToolEnvStatus(value: unknown): ToolEnvStatus | null {
  if (!isRecord(value)) {
    return null;
  }
  const toolId = safeText(value.tool_id);
  if (!toolId) {
    return null;
  }
  return {
    tool_id: toolId,
    name: safeText(value.name, toolId),
    env_name: safeText(value.env_name),
    version: safeText(value.version),
    installed: Boolean(value.installed),
    installable: Boolean(value.installable),
    status: safeText(value.status, "unknown"),
    message: safeText(value.message),
    job_id: safeText(value.job_id),
    log_text: safeText(value.log_text),
    log_size: Number(value.log_size || 0),
    shared_tool_ids: Array.isArray(value.shared_tool_ids) ? value.shared_tool_ids.map((item) => safeText(item)).filter(Boolean) : [],
  };
}

export function parseMiniforgeStatus(value: unknown): MiniforgeStatus | null {
  if (!isRecord(value)) {
    return null;
  }
  return {
    installed: Boolean(value.installed),
    status: safeText(value.status, "unknown"),
    version: safeText(value.version),
    conda_executable: safeText(value.conda_executable),
    message: safeText(value.message),
    job_id: safeText(value.job_id),
    log_text: safeText(value.log_text),
    task_status: isRecord(value.task_status) ? value.task_status : {},
  };
}

export function parseRemoteEnvStatus(value: unknown): RemoteEnvStatus | null {
  if (!isRecord(value)) {
    return null;
  }
  const miniforge = parseMiniforgeStatus(value.miniforge);
  if (!miniforge) {
    return null;
  }
  const summary = isRecord(value.summary) ? value.summary : {};
  return {
    miniforge,
    tool_envs: Array.isArray(value.tool_envs)
      ? value.tool_envs.map(toToolEnvStatus).filter((item: ToolEnvStatus | null): item is ToolEnvStatus => !!item)
      : [],
    summary: {
      total: Number(summary.total || 0),
      installed: Number(summary.installed || 0),
      missing: Number(summary.missing || 0),
      env_paths: Array.isArray(summary.env_paths) ? summary.env_paths.map((item) => safeText(item)).filter(Boolean) : [],
    },
  };
}

export function parseInstallJobSnapshot(value: unknown): InstallJobSnapshot | null {
  if (!isRecord(value)) {
    return null;
  }
  const jobId = safeText(value.job_id);
  if (!jobId) {
    return null;
  }
  return {
    job_id: jobId,
    status: safeText(value.status, "unknown"),
    done: Boolean(value.done),
    ok: Boolean(value.ok),
    exit_code: safeText(value.exit_code),
    heartbeat: safeText(value.heartbeat),
    log_text: safeText(value.log_text),
    log_lines: Array.isArray(value.log_lines) ? value.log_lines.map((item) => safeText(item)).filter(Boolean) : [],
    progress: isRecord(value.progress) ? value.progress : {},
    message: safeText(value.message),
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
    auto_connect_attempted: Boolean(value.auto_connect_attempted),
    auto_connect_failed: Boolean(value.auto_connect_failed),
    auto_connect_error: safeText(value.auto_connect_error) || undefined,
    auto_connect_notice_key: safeText(value.auto_connect_notice_key) || undefined,
  };
}

export function parseWorkflowCompilePreview(value: unknown): WorkflowCompilePreview | null {
  if (!isRecord(value)) {
    return null;
  }
  const bundleId = safeText(value.bundle_id);
  if (!bundleId) {
    return null;
  }
  const files: Record<string, string> = {};
  if (isRecord(value.files)) {
    for (const [key, item] of Object.entries(value.files)) {
      const normalizedKey = safeText(key);
      if (normalizedKey) {
        files[normalizedKey] = safeText(item);
      }
    }
  }
  return {
    bundle_id: bundleId,
    files,
    manifest: isRecord(value.manifest) ? value.manifest : {},
  };
}

export function toWorkflowArtifact(value: unknown): WorkflowArtifact | null {
  if (!isRecord(value)) {
    return null;
  }
  const name = safeText(value.name);
  if (!name) {
    return null;
  }
  return {
    name,
    remote_path: safeText(value.remote_path),
    local_path: safeText(value.local_path),
    available: Boolean(value.available),
    kind: safeText(value.kind || value.artifact_type) || undefined,
    artifact_type: safeText(value.artifact_type) || undefined,
    display_role: safeText(value.display_role) || undefined,
    viewer_hint: safeText(value.viewer_hint) || undefined,
    content_type: safeText(value.content_type) || undefined,
    error: safeText(value.error) || undefined,
  };
}

export function toWorkflowResult(value: unknown): WorkflowResult | null {
  if (!isRecord(value)) {
    return null;
  }
  const resultId = safeText(value.result_id);
  if (!resultId) {
    return null;
  }
  return {
    result_id: resultId,
    task_id: safeText(value.task_id),
    run_id: safeText(value.run_id),
    kind: safeText(value.kind, "artifacts"),
    summary: isRecord(value.summary) ? value.summary : {},
    content_type: safeText(value.content_type, "application/json"),
    viewer_kind: safeText(value.viewer_kind, "json"),
    content_url: safeText(value.content_url),
    created_at: Number(value.created_at || 0),
    updated_at: Number(value.updated_at || 0),
    result_path: safeText(value.result_path),
  };
}

export function toWorkflowRun(value: unknown): WorkflowRun | null {
  if (!isRecord(value)) {
    return null;
  }
  const runId = safeText(value.run_id);
  if (!runId) {
    return null;
  }
  return {
    run_id: runId,
    project_id: safeText(value.project_id),
    workflow_id: safeText(value.workflow_id),
    profile_id: safeText(value.profile_id),
    status: safeText(value.status, "unknown"),
    created_at: Number(value.created_at || 0),
    updated_at: Number(value.updated_at || 0),
    bundle_id: safeText(value.bundle_id),
    message: safeText(value.message),
    local_bundle_dir: safeText(value.local_bundle_dir) || undefined,
    local_run_dir: safeText(value.local_run_dir) || undefined,
    remote_task_dir: safeText(value.remote_task_dir) || undefined,
    remote_bundle_dir: safeText(value.remote_bundle_dir) || undefined,
    remote_work_dir: safeText(value.remote_work_dir) || undefined,
    remote_output_dir: safeText(value.remote_output_dir) || undefined,
    launcher_pid: safeText(value.launcher_pid) || undefined,
    nextflow_pid: safeText(value.nextflow_pid) || undefined,
    resolved_config_path: safeText(value.resolved_config_path) || undefined,
    backend_kind: safeText(value.backend_kind) || undefined,
    executor: safeText(value.executor) || undefined,
    packaging_mode: safeText(value.packaging_mode) || undefined,
    container_runtime: safeText(value.container_runtime) || undefined,
    scheduler_job_id: safeText(value.scheduler_job_id) || undefined,
    remote_status: isRecord(value.remote_status) ? value.remote_status : undefined,
    artifacts: Array.isArray(value.artifacts)
      ? value.artifacts.map(toWorkflowArtifact).filter((item: WorkflowArtifact | null): item is WorkflowArtifact => !!item)
      : [],
  };
}

export function parseWorkflowServerProfile(value: unknown): WorkflowServerProfile | null {
  if (!isRecord(value)) {
    return null;
  }
  const profileId = safeText(value.profile_id);
  if (!profileId) {
    return null;
  }
  const packagingMode = safeText(value.packaging_mode) as WorkflowServerProfile["packaging_mode"];
  if (packagingMode !== "container" && packagingMode !== "conda") {
    return null;
  }
  return {
    profile_id: profileId,
    server_id: safeText(value.server_id, "current"),
    profile_kind: safeText(value.profile_kind, profileId),
    executor: safeText(value.executor),
    packaging_mode: packagingMode,
    container_runtime: safeText(value.container_runtime),
    work_dir: safeText(value.work_dir),
    output_dir: safeText(value.output_dir),
    cache_dir: safeText(value.cache_dir),
  };
}

function parseRuntimeCapability(value: unknown): { available: boolean; version?: string } {
  if (!isRecord(value)) {
    return { available: false };
  }
  const version = safeText(value.version);
  return {
    available: Boolean(value.available),
    version: version || undefined,
  };
}

export function parseWorkflowRuntimeCapabilities(value: unknown): WorkflowRuntimeCapabilities | null {
  if (!isRecord(value)) {
    return null;
  }
  return {
    java: parseRuntimeCapability(value.java),
    nextflow: parseRuntimeCapability(value.nextflow),
    docker: parseRuntimeCapability(value.docker),
    podman: parseRuntimeCapability(value.podman),
    apptainer: parseRuntimeCapability(value.apptainer),
    micromamba: parseRuntimeCapability(value.micromamba),
    conda: parseRuntimeCapability(value.conda),
    sbatch: parseRuntimeCapability(value.sbatch),
  };
}

export function parseServerDoctorReport(value: unknown): ServerDoctorReport | null {
  if (!isRecord(value)) {
    return null;
  }
  const serverId = safeText(value.server_id);
  if (!serverId) {
    return null;
  }
  return {
    server_id: serverId,
    doctor_phase: safeText(value.doctor_phase),
    recommended_profile: safeText(value.recommended_profile),
    recommended_profile_details: parseWorkflowServerProfile(value.recommended_profile_details),
    runtime_capabilities: parseWorkflowRuntimeCapabilities(value.runtime_capabilities),
    preflight: parsePreflightResult(value.preflight),
    env_status: parseRemoteEnvStatus(value.env_status),
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
