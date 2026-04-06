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
  tool_id: string;
  sample_id: string;
  status: string;
  created_at: number;
  sample_name?: string;
  parameters?: string;
  error?: string;
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

export type TabId = "tools" | "history" | "integrated" | "database";
