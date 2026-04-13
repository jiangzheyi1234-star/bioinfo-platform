"use client";

export type Project = {
  project_id: string;
  name: string;
  status: string;
  description: string;
  last_opened_at: number;
};

export type Execution = {
  execution_id: string;
  task_id?: string;
  tool_id: string;
  sample_id: string;
  status: string;
  created_at: number;
  sample_name?: string;
  parameters?: string;
  error?: string;
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

export type ToolSummary = {
  id: string;
  name: string;
  category: string;
  description: string;
};

export type ToolDescriptor = {
  id: string;
  name: string;
  category?: string;
  version?: string;
  description?: string;
  [key: string]: unknown;
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

export type TabId =
  | "projects"
  | "samples"
  | "runs"
  | "history"
  | "databases"
  | "connect"
  | "toolflows"
  | "settings"
  | "workbench";
