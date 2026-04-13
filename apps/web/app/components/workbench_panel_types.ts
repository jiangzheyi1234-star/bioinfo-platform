export type WorkbenchHistoryRow = {
  execution_id: string;
  sample_id: string;
  sample_name?: string;
  tool_id: string;
  status: string;
};

export type WorkbenchConfig = {
  features?: Array<Record<string, unknown>>;
  views?: Record<string, Record<string, unknown>>;
  [key: string]: unknown;
};

export type WorkbenchFeature = {
  id: string;
  title: string;
  description: string;
  badge: string;
  status: string;
};

export type WorkbenchView = Record<string, unknown>;

export type ConfiguredDatabasePath = {
  key: string;
  path: string;
  label: string;
};

export type SummaryPair = {
  key: string;
  value: string;
};

export type SummaryItem = {
  label: string;
  value: string;
  tone: string;
};

export type TableColumn = {
  key: string;
  label: string;
};

export type TableRow = Record<string, string>;

export type TableModel = {
  title: string;
  subtitle: string;
  columns: TableColumn[];
  rows: TableRow[];
};

export type ArtifactItem = {
  name: string;
  local_path: string;
  remote_path: string;
  available: boolean;
  display_role: string;
  viewer_hint: string;
};

export type ProvenanceItem = {
  label: string;
  value: string;
};

export type ResultTab = "table" | "chart" | "artifacts" | "provenance";

export type ViewSourceMode = "workflow" | "history";

export type WorkbenchRemoteExecutionStatus = {
  execution_id: string;
  tool_id: string;
  sample_id: string;
  local_status: string;
  created_at: number | null;
  completed_at: number | null;
  local_error: string;
  task_dir: string;
  ssh_connected: boolean;
  screen_running: boolean | null;
  remote_status: string;
  exit_code: string;
  heartbeat: string;
  heartbeat_age_sec: number | null;
  log_tail: string;
  response_status: string;
  response_message: string;
};

export type WorkbenchTaskRuntimeState = "ready" | "running" | "repair-required" | "blocked" | "awaiting-decision";

export type WorkbenchTaskGuidance = {
  state: WorkbenchTaskRuntimeState;
  label: string;
  summary: string;
  details: string[];
  recommended_action: string;
};
