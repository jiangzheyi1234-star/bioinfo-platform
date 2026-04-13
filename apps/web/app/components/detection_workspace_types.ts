"use client";

export type Project = {
  project_id: string;
  name: string;
  status: string;
  description: string;
  last_opened_at: number;
};

export type Task = {
  task_id: string;
  project_id: string;
  title: string;
  description: string;
  status: string;
  created_at: number;
  updated_at: number;
  last_activity_at: number;
  latest_execution_id: string;
  summary: string;
  result_snapshot: Record<string, unknown>;
  execution_count: number;
  failed_execution_count: number;
  latest_execution_created_at: number;
};

export type DatabaseEntry = {
  db_id: string;
  name: string;
  category: string;
  description?: string;
  resolved_path: string;
  configured_override: string;
  installable: boolean;
  install_job_id?: string;
  install_stage?: string;
  status?: string;
  status_message?: string;
};

export type Sample = {
  sample_id: string;
  name: string;
  source?: string;
  metadata: Record<string, unknown>;
};

export type SettingsPayload = Record<string, unknown>;

export type SSHSettings = {
  host: string;
  port: number;
  user: string;
  password: string;
  use_key: boolean;
  key_file: string;
};

export type SSHStatus = {
  configured: boolean;
  connected: boolean;
  host: string;
  port: number;
  user: string;
  use_key: boolean;
  key_file: string;
  has_password: boolean;
  message: string;
  auto_connect_attempted?: boolean;
  auto_connect_failed?: boolean;
  auto_connect_error?: string;
  auto_connect_notice_key?: string;
};

export type SSHDiagnosticStep = {
  name: string;
  status: "ok" | "fail" | "running";
  message: string;
};

export type PreflightCheck = {
  key: string;
  label: string;
  status: "ok" | "warn" | "fail";
  value: string;
  message: string;
};

export type PreflightResult = {
  ok: boolean;
  arch: string;
  free_disk_gb: number;
  recommended_profile: string;
  recommended_profile_details: WorkflowServerProfile | null;
  runtime_capabilities: WorkflowRuntimeCapabilities | null;
  checks: PreflightCheck[];
  failures: string[];
  warnings: string[];
};

export type ToolEnvStatus = {
  tool_id: string;
  name: string;
  env_name: string;
  version: string;
  installed: boolean;
  installable: boolean;
  status: string;
  message: string;
  job_id: string;
  log_text: string;
  log_size: number;
  shared_tool_ids: string[];
};

export type MiniforgeStatus = {
  installed: boolean;
  status: string;
  version: string;
  conda_executable: string;
  message: string;
  job_id: string;
  log_text: string;
  task_status: Record<string, unknown>;
};

export type RemoteEnvStatus = {
  miniforge: MiniforgeStatus;
  tool_envs: ToolEnvStatus[];
  summary: {
    total: number;
    installed: number;
    missing: number;
    env_paths: string[];
  };
};

export type InstallJobSnapshot = {
  job_id: string;
  status: string;
  done: boolean;
  ok: boolean;
  exit_code: string;
  heartbeat: string;
  log_text: string;
  log_lines: string[];
  progress: Record<string, unknown>;
  message: string;
};

export type RuntimeEvent = {
  seq: number;
  event_type: string;
  timestamp: number;
  payload: Record<string, unknown>;
};

export type AppLogPayload = {
  path: string;
  lines: string[];
};

export type WorkflowNodeView = {
  node_id: string;
  tool_id: string;
  label: string;
  params: Record<string, unknown>;
};

export type WorkflowEdgeView = {
  edge_id: string;
  source_node_id: string;
  target_node_id: string;
  output_name: string;
  input_name: string;
};

export type WorkflowSpecView = {
  workflow_id: string;
  name: string;
  version: string;
  nodes: WorkflowNodeView[];
  edges: WorkflowEdgeView[];
  params_schema: Record<string, unknown>;
};

export type WorkflowServerProfile = {
  profile_id: string;
  server_id: string;
  profile_kind: string;
  executor: string;
  packaging_mode: "container" | "conda";
  container_runtime: string;
  work_dir: string;
  output_dir: string;
  cache_dir: string;
};

export type WorkflowRuntimeCapability = {
  available: boolean;
  version?: string;
};

export type WorkflowRuntimeCapabilities = {
  java: WorkflowRuntimeCapability;
  nextflow: WorkflowRuntimeCapability;
  docker: WorkflowRuntimeCapability;
  podman: WorkflowRuntimeCapability;
  apptainer: WorkflowRuntimeCapability;
  micromamba: WorkflowRuntimeCapability;
  conda: WorkflowRuntimeCapability;
  sbatch: WorkflowRuntimeCapability;
};

export type WorkflowCompilePreview = {
  bundle_id: string;
  files: Record<string, string>;
  manifest: Record<string, unknown>;
};

export type WorkflowArtifact = {
  name: string;
  remote_path: string;
  local_path: string;
  available: boolean;
  kind?: string;
  content_type?: string;
  error?: string;
};

export type WorkflowRun = {
  run_id: string;
  project_id: string;
  workflow_id: string;
  profile_id: string;
  status: string;
  created_at: number;
  updated_at: number;
  bundle_id: string;
  message: string;
  local_bundle_dir?: string;
  local_run_dir?: string;
  remote_task_dir?: string;
  remote_bundle_dir?: string;
  remote_work_dir?: string;
  remote_output_dir?: string;
  launcher_pid?: string;
  nextflow_pid?: string;
  resolved_config_path?: string;
  backend_kind?: string;
  executor?: string;
  packaging_mode?: string;
  container_runtime?: string;
  scheduler_job_id?: string;
  remote_status?: Record<string, unknown>;
  artifacts: WorkflowArtifact[];
};

export type ServerDoctorReport = {
  server_id: string;
  doctor_phase: string;
  recommended_profile: string;
  recommended_profile_details: WorkflowServerProfile | null;
  runtime_capabilities: WorkflowRuntimeCapabilities | null;
  preflight: PreflightResult | null;
  env_status: RemoteEnvStatus | null;
};

export type TabId =
  | "runs"
  | "connect"
  | "workspace"
  | "workflows"
  | "artifacts"
  | "settings";
