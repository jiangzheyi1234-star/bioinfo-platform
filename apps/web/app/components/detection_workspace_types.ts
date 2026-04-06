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
  resolved_path: string;
  configured_override: string;
  installable: boolean;
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
};

export type SSHDiagnosticStep = {
  name: string;
  status: "ok" | "fail" | "running";
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

export type TabId = "projects" | "samples" | "runs" | "history" | "databases" | "settings" | "workbench";
