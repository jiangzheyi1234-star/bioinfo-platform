"use client";

import { LocalApiError, apiBase } from "@/app/lib/local-api-client";

export type SSHStatus = {
  configured: boolean;
  connected: boolean;
  auth_mode?: "password_ref" | "key_file" | "ssh_config" | "agent";
  ssh_host_alias?: string;
  identity_ref?: string;
  remember_auth?: boolean;
  host: string;
  port: number;
  user: string;
  has_password: boolean;
  timeout_sec?: number;
  auto_connect_on_startup?: boolean;
  message: string;
  connecting?: boolean;
  auto_connect_attempted?: boolean;
  auto_connect_in_progress?: boolean;
  auto_connect_failed?: boolean;
  auto_connect_error?: string;
  runner?: {
    state: "preparing" | "ready" | "repair_needed" | "failed" | string;
    ready: boolean;
    message: string;
    reasonCode: string;
    deploymentAction?: string;
    servicePort?: number;
    tunnelPort?: number;
  };
};

export type SSHFormState = {
  auth_mode: "password_ref" | "key_file" | "ssh_config" | "agent";
  ssh_host_alias: string;
  host: string;
  port: string;
  user: string;
  password: string;
  identity_ref: string;
  remember_auth: boolean;
  auto_connect_on_startup: boolean;
  timeout_sec: string;
};

export type TerminalSnapshot = {
  session_id: string;
  cursor: number;
  output: string;
  connected: boolean;
  input_enabled: boolean;
  closed: boolean;
  message: string;
  created_at: number;
  closed_at: number | null;
};

export type TerminalDisposable = { dispose: () => void };

export type FitAddonLike = {
  fit: () => void;
};

export type TerminalThemeLike = {
  background: string;
  foreground: string;
  cursor: string;
  selectionBackground: string;
  black: string;
  red: string;
  green: string;
  yellow: string;
  blue: string;
  magenta: string;
  cyan: string;
  white: string;
  brightBlack: string;
  brightRed: string;
  brightGreen: string;
  brightYellow: string;
  brightBlue: string;
  brightMagenta: string;
  brightCyan: string;
  brightWhite: string;
};

export type XTermLike = {
  open: (element: HTMLElement) => void;
  write: (data: string) => void;
  reset: () => void;
  focus: () => void;
  dispose: () => void;
  loadAddon: (addon: FitAddonLike) => void;
  onData: (handler: (data: string) => void) => TerminalDisposable;
  onSelectionChange?: (handler: () => void) => TerminalDisposable;
  hasSelection?: () => boolean;
  getSelection?: () => string;
  clearSelection?: () => void;
  attachCustomKeyEventHandler?: (handler: (event: KeyboardEvent) => boolean) => void;
  cols?: number;
  rows?: number;
  options: {
    disableStdin?: boolean;
    theme?: TerminalThemeLike;
  };
};

export type TerminalHandle = {
  terminal: XTermLike;
  fitAddon: FitAddonLike;
  disposed: boolean;
};

export type SshShellContextValue = {
  status: SSHStatus | null;
  loading: boolean;
  dialogOpen: boolean;
  setDialogOpen: (open: boolean) => void;
  form: SSHFormState;
  setForm: React.Dispatch<React.SetStateAction<SSHFormState>>;
  connectBusy: boolean;
  disconnectBusy: boolean;
  formError: string;
  clearFormError: () => void;
  submitConnect: () => Promise<void>;
  submitDisconnect: () => Promise<void>;
};

export const defaultForm: SSHFormState = {
  auth_mode: "password_ref",
  ssh_host_alias: "",
  host: "",
  port: "22",
  user: "",
  password: "",
  identity_ref: "",
  remember_auth: true,
  auto_connect_on_startup: false,
  timeout_sec: "5",
};

export const TERMINAL_HEIGHT_KEY = "h2ometa:ssh-terminal-height";
export const TERMINAL_FONT_SIZE = 13;
export const TERMINAL_LINE_HEIGHT = 1.4;
const TERMINAL_HEADER_HEIGHT = 44;
const TERMINAL_BODY_VERTICAL_PADDING = 8;
const MIN_TERMINAL_ROWS = 12;
const MIN_TERMINAL_HEIGHT = Math.ceil(
  TERMINAL_HEADER_HEIGHT + TERMINAL_BODY_VERTICAL_PADDING + MIN_TERMINAL_ROWS * TERMINAL_FONT_SIZE * TERMINAL_LINE_HEIGHT
);
export const DEFAULT_TERMINAL_HEIGHT = 220;
const TERMINAL_VIEWPORT_MARGIN = 180;
const MIN_TERMINAL_COLS = 80;

export const LIGHT_TERMINAL_THEME: TerminalThemeLike = {
  background: "#ffffff",
  foreground: "#334155",
  cursor: "#94a3b8",
  selectionBackground: "#dbeafe",
  black: "#0f172a",
  red: "#dc2626",
  green: "#15803d",
  yellow: "#ca8a04",
  blue: "#2563eb",
  magenta: "#9333ea",
  cyan: "#0891b2",
  white: "#e2e8f0",
  brightBlack: "#64748b",
  brightRed: "#ef4444",
  brightGreen: "#22c55e",
  brightYellow: "#eab308",
  brightBlue: "#3b82f6",
  brightMagenta: "#a855f7",
  brightCyan: "#06b6d4",
  brightWhite: "#f8fafc",
};

export function toForm(status: SSHStatus | null): SSHFormState {
  if (!status) {
    return defaultForm;
  }
  return {
    auth_mode: status.auth_mode || "password_ref",
    ssh_host_alias: status.ssh_host_alias || "",
    host: status.host || "",
    port: String(status.port || 22),
    user: status.user || "",
    password: "",
    identity_ref: status.identity_ref || "",
    remember_auth: status.remember_auth ?? true,
    auto_connect_on_startup: Boolean(status.auto_connect_on_startup),
    timeout_sec: String(status.timeout_sec || 5),
  };
}

export function normalizeFetchError(error: unknown): string {
  if (error instanceof LocalApiError) {
    return error.message || "请求失败";
  }
  const message = error instanceof Error ? error.message : String(error || "");
  if (message.includes("Failed to fetch") || message.includes("NetworkError") || message.includes("Load failed")) {
    return `本地 API 未启动或不可达：${apiBase()}`;
  }
  return message || "请求失败";
}

function maxTerminalHeight(): number {
  if (typeof window === "undefined") {
    return 620;
  }
  return Math.max(MIN_TERMINAL_HEIGHT, window.innerHeight - TERMINAL_VIEWPORT_MARGIN);
}

export function clampTerminalHeight(value: number): number {
  return Math.max(MIN_TERMINAL_HEIGHT, Math.min(maxTerminalHeight(), Math.round(value)));
}

function clampTerminalCols(value: number): number {
  return Math.max(MIN_TERMINAL_COLS, Math.round(value));
}

function clampTerminalRows(value: number): number {
  return Math.max(MIN_TERMINAL_ROWS, Math.round(value));
}

export function readStoredTerminalHeight(): number {
  if (typeof window === "undefined") {
    return DEFAULT_TERMINAL_HEIGHT;
  }
  const raw = window.localStorage.getItem(TERMINAL_HEIGHT_KEY);
  if (!raw) {
    return DEFAULT_TERMINAL_HEIGHT;
  }
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) {
    window.localStorage.removeItem(TERMINAL_HEIGHT_KEY);
    return DEFAULT_TERMINAL_HEIGHT;
  }
  return clampTerminalHeight(parsed);
}

export function getTerminalGridSize(terminal: XTermLike | null | undefined): { cols: number; rows: number } {
  return {
    cols: clampTerminalCols(terminal?.cols || 120),
    rows: clampTerminalRows(terminal?.rows || 28),
  };
}

export function isTerminalHandleActive(handle: TerminalHandle | null | undefined): handle is TerminalHandle {
  return Boolean(handle && !handle.disposed);
}

export function reorderItemsById<T extends { id: string }>(
  items: readonly T[],
  draggedId: string,
  targetId: string,
  placement: "before" | "after"
): T[] {
  if (draggedId === targetId) {
    return [...items];
  }

  const draggedItem = items.find((item) => item.id === draggedId);
  if (!draggedItem) {
    return [...items];
  }

  const remaining = items.filter((item) => item.id !== draggedId);
  const targetIndex = remaining.findIndex((item) => item.id === targetId);
  if (targetIndex < 0) {
    return [...items];
  }

  const insertIndex = placement === "before" ? targetIndex : targetIndex + 1;
  return [...remaining.slice(0, insertIndex), draggedItem, ...remaining.slice(insertIndex)];
}
