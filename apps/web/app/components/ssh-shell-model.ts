"use client";

import { LocalApiError, apiBase } from "@/app/lib/local-api-client";

export type RunnerLifecycleStatus = {
  state: "preparing" | "ready" | "repair_needed" | "failed" | "stopped" | string;
  ready: boolean;
  message: string;
  reasonCode: string;
  deploymentAction?: string;
  servicePort?: number;
  tunnelPort?: number;
};

export type RunnerRepairStatus = {
  connected: boolean;
  connecting?: boolean;
  auto_connect_in_progress?: boolean;
  displayTarget?: string;
  host?: string;
  message?: string;
  serverId?: string;
  runner?: RunnerLifecycleStatus;
};

export type SSHStatus = RunnerRepairStatus & {
  configured: boolean;
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
  auto_connect_attempted?: boolean;
  auto_connect_failed?: boolean;
  auto_connect_error?: string;
  message: string;
};

export type RemoteStatusView = {
  label: string;
  message: string;
  dotClass: string;
  toneClass: string;
  stages: string[];
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

export type SSHHostKeyCandidate = {
  serverId: string;
  host: string;
  port: number;
  hostKeyType: string;
  hostKeyFingerprintSha256: string;
  knownHostsPath: string;
};

export type TerminalSnapshot = {
  session_id: string;
  cursor: number;
  base_cursor: number;
  output: string;
  truncated: boolean;
  scrollback_limit: number;
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

export function isSshChannelReady(status: RunnerRepairStatus | null | undefined): boolean {
  return Boolean(status?.connected && !status.connecting && !status.auto_connect_in_progress);
}

export const MANUAL_RUNNER_STOP_REASON = "RUNNER_STOPPED";

export function isRunnerManuallyStopped(status: RunnerRepairStatus | null | undefined): boolean {
  const runner = status?.runner;
  return Boolean(
    status?.connected &&
      runner &&
      !runner.ready &&
      (runner.state === "stopped" || runner.reasonCode === MANUAL_RUNNER_STOP_REASON)
  );
}

export function isRunnerRepairRequired(status: RunnerRepairStatus | null | undefined): boolean {
  const runner = status?.runner;
  return Boolean(
    status?.connected &&
      runner &&
      !runner.ready &&
      (runner.state === "repair_needed" || runner.state === "failed")
  );
}

export function isRunnerPreparing(status: RunnerRepairStatus | null | undefined): boolean {
  const runner = status?.runner;
  return Boolean(
    status?.connected &&
      runner &&
      !runner.ready &&
      !isRunnerManuallyStopped(status) &&
      !isRunnerRepairRequired(status)
  );
}

export function resolveRemoteStatus(status: RunnerRepairStatus | null): RemoteStatusView {
  if (status?.connecting || status?.auto_connect_in_progress) {
    const target = remoteStatusTarget(status);
    return {
      label: "SSH 连接中",
      message: target,
      dotClass: "animate-pulse bg-blue-500",
      toneClass: "text-blue-700",
      stages: ["正在建立 SSH 连接", "等待认证结果", "连接成功后准备远程服务"],
    };
  }
  if (!status?.connected) {
    return {
      label: "未连接",
      message: "",
      dotClass: "bg-slate-300",
      toneClass: "text-slate-500",
      stages: ["SSH 未连接", "远程服务未启动"],
    };
  }
  const target = remoteStatusTarget(status);
  if (!status.runner) {
    return {
      label: "SSH 已连接",
      message: "正在检查远程服务...",
      dotClass: "animate-pulse bg-blue-500",
      toneClass: "text-blue-700",
      stages: ["SSH 已连接", "正在检查远程服务", "正在打开安全通道"],
    };
  }
  if (status.runner.ready) {
    return {
      label: "已连接",
      message: target,
      dotClass: "bg-emerald-500",
      toneClass: "text-blue-700",
      stages: ["SSH 已连接", "远程服务已就绪", "安全通道已打开", "健康检查通过"],
    };
  }
  if (isRunnerManuallyStopped(status)) {
    return {
      label: "远程服务已停止",
      message: status.runner.message || "远程服务已手动停止",
      dotClass: "bg-slate-400",
      toneClass: "text-slate-700",
      stages: ["SSH 已连接", "远程服务已手动停止", "等待手动启动"],
    };
  }
  if (status.runner.state === "recovering") {
    return {
      label: "SSH 已连接",
      message: status.runner.message || "远程服务正在恢复...",
      dotClass: "animate-pulse bg-blue-500",
      toneClass: "text-blue-700",
      stages: ["SSH 已连接", "远程服务正在恢复", "正在重建安全通道"],
    };
  }
  const failed = isRunnerRepairRequired(status);
  return {
    label: failed ? "远程服务需要修复" : "SSH 已连接",
    message: status.runner.message || "",
    dotClass: failed ? "bg-amber-500" : "animate-pulse bg-blue-500",
    toneClass: failed ? "text-amber-700" : "text-blue-700",
    stages: failed
      ? ["SSH 已连接", "远程服务需要修复", status.runner.reasonCode || "请查看详情"]
      : ["SSH 已连接", "正在检查远程服务", "正在同步环境", "正在启动远程服务", "正在打开安全通道"],
  };
}

export function runnerEnsureActionLabel(status: RunnerRepairStatus | null | undefined, busy: boolean): string {
  if (isRunnerManuallyStopped(status)) {
    return busy ? "启动中" : "启动远程服务";
  }
  if (isRunnerRepairRequired(status)) {
    return busy ? "修复中" : "修复远程服务";
  }
  return busy ? "准备中" : "准备远程服务";
}

export function runnerSidebarSubcopy(status: RunnerRepairStatus | null | undefined): string {
  if (isRunnerManuallyStopped(status)) {
    return "远程服务已手动停止";
  }
  if (isRunnerRepairRequired(status)) {
    return "远程服务需要修复";
  }
  return "远程服务准备中";
}

function remoteStatusTarget(status: RunnerRepairStatus): string {
  if (status.displayTarget) {
    return status.displayTarget;
  }
  return status.host ? `SSH: ${status.host}` : "SSH";
}

export const TERMINAL_XTERM_SCROLLBACK_ROWS = 4000;
export const TERMINAL_REPLAY_BUFFER_MAX_CHARS = 512 * 1024;
export const TERMINAL_PENDING_INPUT_MAX_CHARS = 16 * 1024;

export function retainTerminalReplayBufferTail(value: string): string {
  return value.length <= TERMINAL_REPLAY_BUFFER_MAX_CHARS
    ? value
    : value.slice(value.length - TERMINAL_REPLAY_BUFFER_MAX_CHARS);
}

export function retainTerminalPendingInputPrefix(value: string): string {
  return value.length <= TERMINAL_PENDING_INPUT_MAX_CHARS
    ? value
    : value.slice(0, TERMINAL_PENDING_INPUT_MAX_CHARS);
}

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
