import type {
  ArtifactItem,
  ConfiguredDatabasePath,
  ProvenanceItem,
  ResultTab,
  SummaryItem,
  SummaryPair,
  TableColumn,
  TableModel,
  TableRow,
  WorkbenchConfig,
  WorkbenchFeature,
  WorkbenchHistoryRow,
  WorkbenchView,
} from "./workbench_panel_types";

export function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8765";
}

export async function readJsonOrThrow(resp: Response): Promise<any> {
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(payload?.detail || `HTTP ${resp.status}`);
  }
  return payload;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

export function asText(value: unknown, fallback = ""): string {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed || fallback;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return fallback;
}

function compactJson(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function clip(text: string, maxLen = 160): string {
  return text.length > maxLen ? `${text.slice(0, maxLen - 1)}…` : text;
}

export function summarizePairs(value: unknown): SummaryPair[] {
  if (Array.isArray(value)) {
    return value.slice(0, 6).map((item, idx) => ({
      key: `item_${idx + 1}`,
      value: clip(compactJson(item)),
    }));
  }
  if (isRecord(value)) {
    return Object.entries(value)
      .slice(0, 8)
      .map(([key, entry]) => ({ key, value: clip(compactJson(entry)) }));
  }
  if (value === null || value === undefined || value === "") {
    return [];
  }
  return [{ key: "value", value: clip(compactJson(value)) }];
}

export function parseWorkbenchFeatures(config: WorkbenchConfig | null): WorkbenchFeature[] {
  const raw = config?.features;
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw
    .map((entry) => {
      if (!isRecord(entry)) {
        return null;
      }
      const id =
        asText(entry.feature_id) ||
        asText(entry.id) ||
        asText(entry.key) ||
        asText(entry.tool_id) ||
        asText(entry.name);
      if (!id) {
        return null;
      }
      return {
        id,
        title: asText(entry.title) || asText(entry.name) || id,
        description: asText(entry.description) || asText(entry.summary) || "无说明",
        badge: asText(entry.badge),
        status: asText(entry.status) || "unknown",
      };
    })
    .filter((item): item is WorkbenchFeature => !!item);
}

export function parseWorkbenchViews(config: WorkbenchConfig | null): Record<string, WorkbenchView> {
  const raw = config?.views;
  if (!isRecord(raw)) {
    return {};
  }
  const result: Record<string, WorkbenchView> = {};
  for (const [key, value] of Object.entries(raw)) {
    if (isRecord(value)) {
      result[key] = value;
    }
  }
  return result;
}

export function toWorkbenchHistoryRow(value: unknown): WorkbenchHistoryRow | null {
  if (!isRecord(value)) {
    return null;
  }
  const executionId = asText(value.execution_id);
  if (!executionId) {
    return null;
  }
  return {
    execution_id: executionId,
    sample_id: asText(value.sample_id),
    sample_name: asText(value.sample_name) || undefined,
    tool_id: asText(value.tool_id, "unknown_tool"),
    status: asText(value.status, "unknown"),
  };
}

export function toConfiguredDatabasePath(value: unknown): ConfiguredDatabasePath | null {
  if (!isRecord(value)) {
    return null;
  }
  const key = asText(value.key);
  if (!key) {
    return null;
  }
  return {
    key,
    path: asText(value.path),
    label: asText(value.label, key),
  };
}

export function normalizeSummaryItems(value: unknown): SummaryItem[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((entry) => {
      if (!isRecord(entry)) {
        return null;
      }
      const label = asText(entry.label);
      if (!label) {
        return null;
      }
      return {
        label,
        value: asText(entry.value, "-"),
        tone: asText(entry.tone, "neutral"),
      };
    })
    .filter((item): item is SummaryItem => !!item);
}

function normalizeTableColumns(rawColumns: unknown): TableColumn[] {
  if (!Array.isArray(rawColumns)) {
    return [];
  }
  const columns: TableColumn[] = [];
  for (const item of rawColumns) {
    if (isRecord(item)) {
      const key = asText(item.key) || asText(item.name);
      if (!key) {
        continue;
      }
      columns.push({ key, label: asText(item.label, key) });
      continue;
    }
    const key = asText(item);
    if (!key) {
      continue;
    }
    columns.push({ key, label: key });
  }
  return columns;
}

function normalizeRowsFromRecordColumns(rows: unknown[], columns: TableColumn[]): TableRow[] {
  return rows.slice(0, 100).map((row) => {
    const result: TableRow = {};
    if (!isRecord(row)) {
      for (const column of columns) {
        result[column.key] = "-";
      }
      return result;
    }
    for (const column of columns) {
      result[column.key] = asText(row[column.key], "-");
    }
    return result;
  });
}

function normalizeRowsFromArrayRows(rows: unknown[], columns: TableColumn[]): TableRow[] {
  return rows.slice(0, 100).map((row) => {
    const result: TableRow = {};
    const normalized = Array.isArray(row) ? row : [];
    columns.forEach((column, index) => {
      result[column.key] = asText(normalized[index], "-");
    });
    return result;
  });
}

export function normalizeTableModel(view: WorkbenchView | null): TableModel {
  const rawTable = isRecord(view?.table) ? (view?.table as Record<string, unknown>) : null;
  if (!rawTable) {
    return { title: "分析结果", subtitle: "分析结果将在此处展示。", columns: [], rows: [] };
  }

  const title = asText(rawTable.title, "分析结果");
  const subtitle = asText(rawTable.subtitle, "分析结果将在此处展示。");
  let columns = normalizeTableColumns(rawTable.columns);
  const rawRows = Array.isArray(rawTable.rows) ? rawTable.rows : [];

  if (columns.length === 0 && rawRows.length > 0) {
    const first = rawRows[0];
    if (isRecord(first)) {
      columns = Object.keys(first)
        .slice(0, 12)
        .map((key) => ({ key, label: key }));
    } else if (Array.isArray(first)) {
      columns = first.slice(0, 12).map((_, idx) => ({ key: `col_${idx + 1}`, label: `col_${idx + 1}` }));
    }
  }

  let rows: TableRow[] = [];
  if (rawRows.length > 0) {
    if (isRecord(rawRows[0])) {
      rows = normalizeRowsFromRecordColumns(rawRows, columns);
    } else if (Array.isArray(rawRows[0])) {
      rows = normalizeRowsFromArrayRows(rawRows, columns);
    }
  }

  return { title, subtitle, columns, rows };
}

export function normalizeArtifacts(view: WorkbenchView | null): ArtifactItem[] {
  const raw = Array.isArray(view?.artifacts) ? view?.artifacts : [];
  return raw
    .map((entry) => {
      if (isRecord(entry)) {
        return {
          name: asText(entry.name, "unnamed_artifact"),
          local_path: asText(entry.local_path),
          remote_path: asText(entry.remote_path),
          available: Boolean(entry.available),
          display_role: asText(entry.display_role),
          viewer_hint: asText(entry.viewer_hint),
        };
      }
      const name = asText(entry);
      if (!name) {
        return null;
      }
      return {
        name,
        local_path: "",
        remote_path: "",
        available: false,
        display_role: "",
        viewer_hint: "",
      };
    })
    .filter((item): item is ArtifactItem => !!item)
    .slice(0, 80);
}

export function normalizeProvenanceItems(view: WorkbenchView | null): ProvenanceItem[] {
  const raw = isRecord(view?.provenance) ? (view?.provenance as Record<string, unknown>) : null;
  if (!raw) {
    return [];
  }

  const items: ProvenanceItem[] = [];
  const parameters = Array.isArray(raw.parameters) ? raw.parameters : [];
  for (const entry of parameters) {
    if (!isRecord(entry)) {
      continue;
    }
    const label = asText(entry.label);
    const value = asText(entry.value);
    if (!label || !value) {
      continue;
    }
    items.push({ label, value });
  }

  const keys: Array<{ key: string; label: string }> = [
    { key: "execution_id", label: "Execution" },
    { key: "tool_version", label: "Tool Version" },
    { key: "remote_result_dir", label: "远端结果目录" },
    { key: "local_result_dir", label: "本地结果目录" },
    { key: "command_preview", label: "Command" },
  ];

  for (const item of keys) {
    const value = asText(raw[item.key]);
    if (!value) {
      continue;
    }
    items.push({ label: item.label, value });
  }
  return items;
}

export function normalizeCharts(view: WorkbenchView | null): unknown[] {
  if (Array.isArray(view?.charts)) {
    return view?.charts.slice(0, 16) || [];
  }
  if (view?.charts) {
    return [view.charts];
  }
  return [];
}

export function getViewToolId(feature: WorkbenchFeature | null, view: WorkbenchView | null): string {
  if (!view) {
    return feature?.id || "";
  }
  const one = asText(view.tool_id) || asText(view.toolId);
  if (one) {
    return one;
  }
  const many = view.tool_ids ?? view.toolIds;
  if (Array.isArray(many) && many.length > 0) {
    return asText(many[0]);
  }
  return feature?.id || "";
}

export function resolveDefaultResultTab(view: WorkbenchView | null): ResultTab {
  const table = normalizeTableModel(view);
  if (table.rows.length > 0 || table.columns.length > 0) {
    return "table";
  }
  const charts = normalizeCharts(view);
  if (charts.length > 0) {
    return "chart";
  }
  const artifacts = normalizeArtifacts(view);
  if (artifacts.length > 0) {
    return "artifacts";
  }
  return "provenance";
}

export function localPathToFileUrl(localPath: string): string {
  const raw = asText(localPath);
  if (!raw) {
    return "";
  }
  const normalized = raw.replace(/\\/g, "/");
  if (/^[a-zA-Z]:\//.test(normalized)) {
    return `file:///${encodeURI(normalized)}`;
  }
  if (normalized.startsWith("/")) {
    return `file://${encodeURI(normalized)}`;
  }
  return encodeURI(normalized);
}

export function compactPreview(value: unknown): string {
  return clip(compactJson(value), 220);
}
