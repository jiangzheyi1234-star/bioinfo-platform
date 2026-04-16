"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { usePathname, useRouter } from "next/navigation";
import { Ellipsis, GripHorizontal, Link2, Terminal as TerminalIcon, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PrepareServerWizard } from "@/app/components/prepare-server-wizard";
import { deriveRuntimeStatus, loadRuntimeInspection, type RuntimeStatus } from "@/app/components/runtime-inspection";
import { LocalApiError, apiBase, requestLocalApiJson } from "@/app/lib/local-api-client";
import { readTerminalClipboard, writeTerminalClipboard } from "@/app/components/ssh-terminal-clipboard";
import {
  openTerminalStream,
  type TerminalStreamClientMessage,
  type TerminalStreamController,
  type TerminalStreamServerMessage,
} from "@/app/components/ssh-terminal-stream";
import { cn } from "@/lib/utils";

type SSHStatus = {
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
};

type SSHFormState = {
  host: string;
  port: string;
  user: string;
  password: string;
  use_key: boolean;
  key_file: string;
  timeout_sec: string;
};

type TerminalSnapshot = {
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

type TerminalDisposable = { dispose: () => void };

type FitAddonLike = {
  fit: () => void;
};

type TerminalThemeLike = {
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

type XTermLike = {
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

type TerminalHandle = {
  terminal: XTermLike;
  fitAddon: FitAddonLike;
};

type SshShellContextValue = {
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

const defaultForm: SSHFormState = {
  host: "",
  port: "22",
  user: "",
  password: "",
  use_key: false,
  key_file: "",
  timeout_sec: "5",
};

const TERMINAL_HEIGHT_KEY = "h2ometa:ssh-terminal-height";
const TERMINAL_FONT_SIZE = 13;
const TERMINAL_LINE_HEIGHT = 1.4;
const TERMINAL_HEADER_HEIGHT = 44;
const TERMINAL_BODY_VERTICAL_PADDING = 8;
const MIN_TERMINAL_ROWS = 12;
const MIN_TERMINAL_HEIGHT = Math.ceil(
  TERMINAL_HEADER_HEIGHT + TERMINAL_BODY_VERTICAL_PADDING + MIN_TERMINAL_ROWS * TERMINAL_FONT_SIZE * TERMINAL_LINE_HEIGHT
);
const DEFAULT_TERMINAL_HEIGHT = 220;
const TERMINAL_VIEWPORT_MARGIN = 180;
const MIN_TERMINAL_COLS = 80;
const LIGHT_TERMINAL_THEME: TerminalThemeLike = {
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

const SshShellContext = createContext<SshShellContextValue | null>(null);

function toForm(status: SSHStatus | null): SSHFormState {
  if (!status) {
    return defaultForm;
  }
  return {
    host: status.host || "",
    port: String(status.port || 22),
    user: status.user || "",
    password: "",
    use_key: Boolean(status.use_key),
    key_file: status.key_file || "",
    timeout_sec: "5",
  };
}

function normalizeFetchError(error: unknown): string {
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

function clampTerminalHeight(value: number): number {
  return Math.max(MIN_TERMINAL_HEIGHT, Math.min(maxTerminalHeight(), Math.round(value)));
}

function clampTerminalCols(value: number): number {
  return Math.max(MIN_TERMINAL_COLS, Math.round(value));
}

function clampTerminalRows(value: number): number {
  return Math.max(MIN_TERMINAL_ROWS, Math.round(value));
}

function readStoredTerminalHeight(): number {
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

function runtimePreparedKey(status: Pick<SSHStatus, "host" | "port" | "user"> | null): string {
  if (!status) {
    return "";
  }
  const host = String(status.host || "").trim().toLowerCase();
  const user = String(status.user || "").trim().toLowerCase();
  const port = Number(status.port || 22);
  if (!host || !user) {
    return "";
  }
  return `${user}@${host}:${port}`;
}

type ResolvedRuntimeState = {
  hostKey?: string;
  nextflowPath?: string;
  javaPath?: string;
  selectedProfile?: string;
  verificationStatus?: string;
};

function getTerminalGridSize(terminal: XTermLike | null | undefined): { cols: number; rows: number } {
  return {
    cols: clampTerminalCols(terminal?.cols || 120),
    rows: clampTerminalRows(terminal?.rows || 28),
  };
}

export function SshShellProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const terminalSurfaceRef = useRef<HTMLDivElement | null>(null);
  const terminalViewportRef = useRef<HTMLDivElement | null>(null);
  const terminalHandleRef = useRef<TerminalHandle | null>(null);
  const terminalStreamRef = useRef<TerminalStreamController | null>(null);
  const terminalReconnectTimerRef = useRef<number | null>(null);
  const terminalReconnectAttemptRef = useRef(0);
  const terminalResizeStateRef = useRef<{ cols: number; rows: number } | null>(null);
  const renderedTerminalOutputRef = useRef("");
  const creatingTerminalSessionRef = useRef(false);
  const terminalCursorRef = useRef(0);
  const terminalSessionIdRef = useRef<string | null>(null);
  const terminalOpenRef = useRef(false);
  const terminalConnectedRef = useRef(false);
  const terminalSessionClosedRef = useRef(false);
  const terminalClosingRef = useRef(false);
  const terminalSelectionRef = useRef("");
  const terminalInputEnabledRef = useRef(false);
  const dragStateRef = useRef<{ startY: number; startHeight: number } | null>(null);
  const lastSilentRuntimeCheckKeyRef = useRef("");

  const [status, setStatus] = useState<SSHStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [prepareDialogOpen, setPrepareDialogOpen] = useState(false);
  const [form, setForm] = useState<SSHFormState>(defaultForm);
  const [connectBusy, setConnectBusy] = useState(false);
  const [disconnectBusy, setDisconnectBusy] = useState(false);
  const [formError, setFormError] = useState("");
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus>("unknown");
  const [resolvedRuntimeState, setResolvedRuntimeState] = useState<ResolvedRuntimeState | null>(null);

  const [terminalOpen, setTerminalOpen] = useState(false);
  const [terminalHeight, setTerminalHeight] = useState(DEFAULT_TERMINAL_HEIGHT);
  const [terminalSessionId, setTerminalSessionId] = useState<string | null>(null);
  const [terminalOutput, setTerminalOutput] = useState("");
  const [terminalMessage, setTerminalMessage] = useState("");
  const [terminalConnected, setTerminalConnected] = useState(false);
  const [terminalInputEnabled, setTerminalInputEnabled] = useState(false);
  const [terminalBusy, setTerminalBusy] = useState(false);
  const [terminalError, setTerminalError] = useState("");
  const [terminalGridLabel, setTerminalGridLabel] = useState("120x28");
  const runtimeIdentityKey = runtimePreparedKey(status);

  const applyTerminalSnapshot = useCallback((item: TerminalSnapshot, mode: "replace" | "append" = "append") => {
    terminalCursorRef.current = item.cursor || 0;
    terminalSessionIdRef.current = item.session_id;
    terminalSessionClosedRef.current = Boolean(item.closed);
    setTerminalSessionId(item.session_id);
    setTerminalMessage(item.message || "");
    setTerminalConnected(Boolean(item.connected));
    setTerminalInputEnabled(Boolean(item.input_enabled));
    setTerminalOutput((current) => {
      const nextChunk = typeof item.output === "string" ? item.output : "";
      return mode === "replace" ? nextChunk : `${current}${nextChunk}`;
    });
  }, []);

  const clearTerminalReconnectTimer = useCallback(() => {
    if (terminalReconnectTimerRef.current !== null) {
      window.clearTimeout(terminalReconnectTimerRef.current);
      terminalReconnectTimerRef.current = null;
    }
  }, []);

  const closeTerminalStream = useCallback(() => {
    clearTerminalReconnectTimer();
    const controller = terminalStreamRef.current;
    terminalStreamRef.current = null;
    if (controller) {
      controller.close();
    }
  }, [clearTerminalReconnectTimer]);

  const resetTerminalState = useCallback(() => {
    closeTerminalStream();
    terminalReconnectAttemptRef.current = 0;
    terminalCursorRef.current = 0;
    terminalSessionIdRef.current = null;
    terminalSessionClosedRef.current = false;
    terminalSelectionRef.current = "";
    setTerminalSessionId(null);
    setTerminalOutput("");
    setTerminalMessage("");
    setTerminalConnected(false);
    setTerminalInputEnabled(false);
    setTerminalBusy(false);
    setTerminalError("");
  }, [closeTerminalStream]);

  const fetchStatus = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!options?.silent) {
        setLoading(true);
      }
      try {
        const data = await requestLocalApiJson("GET", "/api/v1/ssh/status", { cache: "no-store" });
        const next = (data?.item || null) as SSHStatus | null;
        setStatus(next);
        setForm((current) => {
          if (dialogOpen && (current.host || current.user || current.password || current.key_file)) {
            return current;
          }
          setFormError("");
          return toForm(next);
        });
      } catch {
        setStatus(null);
      } finally {
        if (!options?.silent) {
          setLoading(false);
        }
      }
    },
    [dialogOpen]
  );

  useEffect(() => {
    terminalSessionIdRef.current = terminalSessionId;
  }, [terminalSessionId]);

  useEffect(() => {
    terminalOpenRef.current = terminalOpen;
  }, [terminalOpen]);

  useEffect(() => {
    terminalConnectedRef.current = Boolean(status?.connected);
  }, [status?.connected]);

  useEffect(() => {
    terminalInputEnabledRef.current = terminalInputEnabled;
  }, [terminalInputEnabled]);

  useEffect(() => {
    setTerminalHeight(readStoredTerminalHeight());
    void fetchStatus();
  }, [fetchStatus]);

  const detectRuntimeReadiness = useCallback(async (): Promise<RuntimeStatus> => {
    if (!status?.connected) {
      setRuntimeStatus("unknown");
      return "unknown";
    }
    try {
      const inspection = await loadRuntimeInspection();
      const nextStatus = deriveRuntimeStatus(inspection);
      setRuntimeStatus(nextStatus);
      const resolved = inspection.resolvedRuntime || {};
      setResolvedRuntimeState({
        hostKey: String(resolved.host_key || "").trim(),
        nextflowPath: String(resolved.nextflow_path || "").trim(),
        javaPath: String(resolved.java_path || "").trim(),
        selectedProfile: String(resolved.selected_profile || "").trim(),
        verificationStatus: String(resolved.verification_status || "").trim(),
      });
      if (nextStatus === "missing") {
        if (String(resolved.host_key || "").trim() === runtimeIdentityKey && String(resolved.verification_status || "").trim() === "verified") {
          await requestLocalApiJson("PUT", "/api/v1/runtime/resolved", { body: { verification_status: "failed" } }).catch(() => undefined);
          setResolvedRuntimeState((current) => (current ? { ...current, verificationStatus: "failed" } : current));
        }
      }
      return nextStatus;
    } catch {
      setRuntimeStatus("unknown");
      return "unknown";
    }
  }, [status]);

  useEffect(() => {
    if (!status?.connected) {
      setRuntimeStatus("unknown");
      setResolvedRuntimeState(null);
      lastSilentRuntimeCheckKeyRef.current = "";
      return;
    }
    if (!runtimeIdentityKey || lastSilentRuntimeCheckKeyRef.current === runtimeIdentityKey) {
      return;
    }
    lastSilentRuntimeCheckKeyRef.current = runtimeIdentityKey;
    void detectRuntimeReadiness();
  }, [detectRuntimeReadiness, runtimeIdentityKey, status]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void fetchStatus({ silent: true });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [fetchStatus]);

  useEffect(() => {
    return () => {
      terminalClosingRef.current = true;
      closeTerminalStream();
    };
  }, [closeTerminalStream]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(TERMINAL_HEIGHT_KEY, String(terminalHeight));
    }
  }, [terminalHeight]);

  useEffect(() => {
    if (status?.connected || !terminalOpen) {
      return;
    }
    clearTerminalReconnectTimer();
    setTerminalConnected(false);
    setTerminalInputEnabled(false);
    setTerminalMessage("SSH 已断开，终端会话已结束");
  }, [clearTerminalReconnectTimer, status?.connected, terminalOpen]);

  useEffect(() => {
    const onPointerMove = (event: PointerEvent) => {
      const state = dragStateRef.current;
      if (!state) {
        return;
      }
      setTerminalHeight(clampTerminalHeight(state.startHeight - (event.clientY - state.startY)));
    };

    const stopDragging = () => {
      dragStateRef.current = null;
      document.body.classList.remove("ssh-terminal-resizing");
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopDragging);
    window.addEventListener("pointercancel", stopDragging);
    window.addEventListener("blur", stopDragging);

    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopDragging);
      window.removeEventListener("pointercancel", stopDragging);
      window.removeEventListener("blur", stopDragging);
      document.body.classList.remove("ssh-terminal-resizing");
    };
  }, []);

  const sendTerminalStreamMessage = useCallback(
    (message: TerminalStreamClientMessage): boolean => {
      const controller = terminalStreamRef.current;
      if (!controller || controller.socket.readyState !== WebSocket.OPEN) {
        setTerminalError("终端连接不可用，正在尝试重新连接");
        return false;
      }
      const sent = controller.send(message);
      if (!sent) {
        setTerminalError("终端连接不可用，正在尝试重新连接");
      }
      return sent;
    },
    []
  );

  const queueTerminalInput = useCallback(
    (data: string): boolean => {
      if (!data) {
        return false;
      }
      if (!terminalSessionIdRef.current) {
        setTerminalError("终端会话尚未建立");
        return false;
      }
      if (!terminalInputEnabled) {
        setTerminalError(terminalMessage || "SSH 已断开，终端会话已结束");
        return false;
      }
      return sendTerminalStreamMessage({ type: "input", data });
    },
    [sendTerminalStreamMessage, terminalInputEnabled, terminalMessage]
  );

  const waitForTerminalInputReady = useCallback(async (timeoutMs = 3000): Promise<boolean> => {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      if (terminalSessionIdRef.current && terminalInputEnabledRef.current) {
        return true;
      }
      await new Promise<void>((resolve) => window.setTimeout(resolve, 100));
    }
    return Boolean(terminalSessionIdRef.current && terminalInputEnabledRef.current);
  }, []);

  const syncTerminalDimensions = useCallback(
    (handle: TerminalHandle | null, options?: { force?: boolean }) => {
      if (!handle) {
        return;
      }
      handle.fitAddon.fit();
      if (!terminalSessionIdRef.current || terminalSessionClosedRef.current) {
        return;
      }
      const next = getTerminalGridSize(handle.terminal);
      const previous = terminalResizeStateRef.current;
      if (!options?.force && previous && previous.cols === next.cols && previous.rows === next.rows) {
        return;
      }
      terminalResizeStateRef.current = next;
      setTerminalGridLabel(`${next.cols}x${next.rows}`);
      sendTerminalStreamMessage({ type: "resize", cols: next.cols, rows: next.rows });
    },
    [sendTerminalStreamMessage]
  );

  const connectTerminalStream = useCallback(
    (sessionId: string, cursor: number) => {
      if (!sessionId) {
        return;
      }
      clearTerminalReconnectTimer();
      const previous = terminalStreamRef.current;
      terminalStreamRef.current = null;
      if (previous) {
        previous.close();
      }
      const controller = openTerminalStream({
        sessionId,
        cursor,
        onOpen: () => {
          terminalReconnectAttemptRef.current = 0;
          setTerminalError("");
          syncTerminalDimensions(terminalHandleRef.current, { force: true });
        },
        onMessage: (message: TerminalStreamServerMessage) => {
          if (terminalStreamRef.current?.socket !== controller.socket) {
            return;
          }
          switch (message.type) {
            case "ready":
              setTerminalError("");
              return;
            case "output":
              if (!message.data) {
                return;
              }
              terminalCursorRef.current += message.data.length;
              setTerminalOutput((current) => `${current}${message.data}`);
              return;
            case "state":
              setTerminalConnected(Boolean(message.connected));
              setTerminalInputEnabled(Boolean(message.input_enabled));
              setTerminalMessage(message.message || "");
              return;
            case "error":
              setTerminalError(message.message || "终端流错误");
              return;
            case "closed":
              terminalSessionClosedRef.current = true;
              setTerminalConnected(false);
              setTerminalInputEnabled(false);
              setTerminalMessage(message.message || "终端会话已结束");
              return;
            case "pong":
              return;
          }
        },
        onClose: () => {
          if (terminalStreamRef.current?.socket !== controller.socket) {
            return;
          }
          terminalStreamRef.current = null;
          setTerminalInputEnabled(false);
          void fetchStatus({ silent: true });
          if (
            terminalClosingRef.current ||
            terminalSessionClosedRef.current ||
            !terminalConnectedRef.current ||
            !terminalOpenRef.current ||
            terminalSessionIdRef.current !== sessionId
          ) {
            return;
          }
          const attempt = terminalReconnectAttemptRef.current + 1;
          terminalReconnectAttemptRef.current = attempt;
          const delay = Math.min(5000, Math.max(400, attempt * 400));
          setTerminalError("终端连接中断，正在重新连接...");
          clearTerminalReconnectTimer();
          terminalReconnectTimerRef.current = window.setTimeout(() => {
            terminalReconnectTimerRef.current = null;
            if (
              terminalClosingRef.current ||
              terminalSessionClosedRef.current ||
              !terminalOpenRef.current ||
              terminalSessionIdRef.current !== sessionId
            ) {
              return;
            }
            connectTerminalStream(sessionId, terminalCursorRef.current);
          }, delay);
        },
        onError: () => {
          setTerminalError("终端连接异常，正在重连");
        },
      });
      terminalStreamRef.current = controller;
    },
    [clearTerminalReconnectTimer, fetchStatus, syncTerminalDimensions]
  );

  useLayoutEffect(() => {
    if (!terminalOpen) {
      return;
    }
    const node = terminalViewportRef.current;
    if (!node) {
      return;
    }
    let disposed = false;
    let cleanup: (() => void) | null = null;

    void (async () => {
      const [{ Terminal }, { FitAddon }] = await Promise.all([
        import("@xterm/xterm"),
        import("@xterm/addon-fit"),
      ]);
      if (disposed) {
        return;
      }

      const terminal = new Terminal({
        allowProposedApi: false,
        convertEol: false,
        cursorBlink: true,
        cursorStyle: "bar",
        cursorWidth: 2,
        fontFamily:
          '"JetBrains Mono", "SFMono-Regular", ui-monospace, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
        fontSize: TERMINAL_FONT_SIZE,
        lineHeight: TERMINAL_LINE_HEIGHT,
        scrollback: 4000,
        theme: LIGHT_TERMINAL_THEME,
      }) as unknown as XTermLike;
      const fitAddon = new FitAddon();
      terminal.loadAddon(fitAddon);
      terminal.open(node);
      fitAddon.fit();
      terminalHandleRef.current = { terminal, fitAddon };
      terminalResizeStateRef.current = null;
      renderedTerminalOutputRef.current = "";

      const syncSelection = () => {
        terminalSelectionRef.current = terminal.getSelection?.() || "";
      };
      const copySelection = async () => {
        const text = terminal.getSelection?.() || terminalSelectionRef.current;
        if (!text) {
          return false;
        }
        try {
          await writeTerminalClipboard(text);
          terminal.clearSelection?.();
          terminalSelectionRef.current = "";
          setTerminalError("");
        } catch (error) {
          setTerminalError(error instanceof Error ? error.message : "复制终端内容失败");
        }
        return true;
      };
      const pasteClipboard = async () => {
        try {
          const text = await readTerminalClipboard();
          if (!text) {
            return;
          }
          queueTerminalInput(text);
          setTerminalError("");
        } catch (error) {
          setTerminalError(error instanceof Error ? error.message : "粘贴终端内容失败");
        }
      };
      const inputDisposable = terminal.onData((data) => {
        queueTerminalInput(data);
      });
      const selectionDisposable = terminal.onSelectionChange?.(syncSelection);
      terminal.attachCustomKeyEventHandler?.((event) => {
        const isModifier = event.ctrlKey || event.metaKey;
        const normalizedKey = event.key.toLowerCase();
        if (isModifier && normalizedKey === "c" && (terminal.hasSelection?.() || Boolean(terminalSelectionRef.current))) {
          event.preventDefault();
          void copySelection();
          return false;
        }
        if (isModifier && normalizedKey === "v") {
          event.preventDefault();
          void pasteClipboard();
          return false;
        }
        return true;
      });
      const focusTimer = window.setTimeout(() => terminal.focus(), 0);
      const resizeObserver = new ResizeObserver(() => {
        syncTerminalDimensions(terminalHandleRef.current);
      });
      const handlePaste = (event: ClipboardEvent) => {
        const text = event.clipboardData?.getData("text") || "";
        if (!text) {
          return;
        }
        event.preventDefault();
        queueTerminalInput(text);
      };
      resizeObserver.observe(terminalSurfaceRef.current || node);
      node.addEventListener("paste", handlePaste);
      window.requestAnimationFrame(() => {
        syncTerminalDimensions(terminalHandleRef.current, { force: true });
      });

      cleanup = () => {
        window.clearTimeout(focusTimer);
        inputDisposable.dispose();
        selectionDisposable?.dispose();
        resizeObserver.disconnect();
        node.removeEventListener("paste", handlePaste);
        terminalHandleRef.current = null;
        terminalResizeStateRef.current = null;
        renderedTerminalOutputRef.current = "";
        terminalSelectionRef.current = "";
        terminal.dispose();
      };
    })().catch((error: unknown) => {
      if (!disposed) {
        setTerminalError(normalizeFetchError(error) || "终端初始化失败");
      }
    });

    return () => {
      disposed = true;
      cleanup?.();
    };
  }, [queueTerminalInput, syncTerminalDimensions, terminalOpen]);

  useEffect(() => {
    const handle = terminalHandleRef.current;
    if (!handle) {
      return;
    }
    handle.terminal.options.disableStdin = !terminalInputEnabled;
  }, [terminalInputEnabled]);

  useEffect(() => {
    const handle = terminalHandleRef.current;
    if (!handle) {
      return;
    }

    if (!terminalOutput) {
      if (renderedTerminalOutputRef.current) {
        handle.terminal.reset();
        renderedTerminalOutputRef.current = "";
      }
      return;
    }

    const previous = renderedTerminalOutputRef.current;
    if (!previous || !terminalOutput.startsWith(previous)) {
      handle.terminal.reset();
      handle.terminal.write(terminalOutput);
      renderedTerminalOutputRef.current = terminalOutput;
      return;
    }

    const nextChunk = terminalOutput.slice(previous.length);
    if (!nextChunk) {
      return;
    }

    handle.terminal.write(nextChunk);
    renderedTerminalOutputRef.current = terminalOutput;
  }, [terminalOutput]);

  useEffect(() => {
    if (!terminalOpen || !terminalInputEnabled) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      terminalHandleRef.current?.terminal.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [terminalInputEnabled, terminalOpen, terminalSessionId]);

  const persistSettings = useCallback(async () => {
    const payload = {
      patch: {
        ssh: {
          host: form.host.trim(),
          port: Number(form.port || 22),
          user: form.user.trim(),
          password: form.password,
          use_key: form.use_key,
          key_file: form.key_file.trim(),
        },
      },
    };
    await requestLocalApiJson("PUT", "/api/v1/settings", { body: payload });
  }, [form]);

  const selectKeyFile = useCallback(async () => {
    try {
      const selected = await open({
        multiple: false,
        directory: false,
        title: "选择 SSH 密钥文件",
      });
      if (typeof selected === "string" && selected.trim()) {
        setForm((current) => ({ ...current, key_file: selected }));
      }
    } catch (error) {
      setFormError(error instanceof Error ? error.message : String(error || "选择密钥文件失败"));
    }
  }, []);

  const updateField = useCallback(<K extends keyof SSHFormState>(key: K, value: SSHFormState[K]) => {
    setFormError("");
    setForm((current) => ({ ...current, [key]: value }));
  }, []);

  const connectDisabled =
    connectBusy ||
    !form.host.trim() ||
    !form.user.trim() ||
    (form.use_key ? !form.key_file.trim() : !form.password);

  const closeTerminalPanel = useCallback(async () => {
    const activeSessionId = terminalSessionId;
    terminalClosingRef.current = true;
    creatingTerminalSessionRef.current = false;
    setTerminalOpen(false);
    resetTerminalState();
    try {
      if (!activeSessionId) {
        return;
      }
      await requestLocalApiJson("DELETE", `/api/v1/ssh/terminal/sessions/${activeSessionId}`);
    } catch {
      // ignore cleanup failures; local state is already cleared
    } finally {
      terminalClosingRef.current = false;
    }
  }, [resetTerminalState, terminalSessionId]);

  const startTerminalSession = useCallback(
    async (options?: { replaceExisting?: boolean }) => {
      setTerminalOpen(true);
      setTerminalError("");
      if (!status?.connected) {
        setTerminalMessage("请先连接远端服务器");
        setTerminalConnected(false);
        setTerminalInputEnabled(false);
        return;
      }
      if (terminalSessionId && terminalInputEnabled && !options?.replaceExisting) {
        return;
      }
      if (creatingTerminalSessionRef.current) {
        return;
      }
      terminalClosingRef.current = false;
      creatingTerminalSessionRef.current = true;
      setTerminalBusy(true);
      try {
        if (!terminalHandleRef.current) {
          await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
        }
        const { cols, rows } = getTerminalGridSize(terminalHandleRef.current?.terminal);
        if (terminalSessionId) {
          await requestLocalApiJson("DELETE", `/api/v1/ssh/terminal/sessions/${terminalSessionId}`).catch(() => undefined);
          resetTerminalState();
        }
        const data = await requestLocalApiJson("POST", "/api/v1/ssh/terminal/sessions", {
          body: { cols, rows },
        });
        const snapshot = (data?.item || null) as TerminalSnapshot;
        applyTerminalSnapshot(snapshot, "replace");
        terminalSessionClosedRef.current = false;
        connectTerminalStream(snapshot.session_id, snapshot.cursor || 0);
      } catch (error) {
        setTerminalInputEnabled(false);
        setTerminalConnected(false);
        setTerminalError(normalizeFetchError(error) || "远程终端创建失败");
      } finally {
        creatingTerminalSessionRef.current = false;
        setTerminalBusy(false);
      }
    },
    [applyTerminalSnapshot, connectTerminalStream, resetTerminalState, status?.connected, terminalInputEnabled, terminalSessionId]
  );

  const sendTerminalCommand = useCallback(
    async (command: string): Promise<boolean> => {
      const nextCommand = String(command || "").trim();
      if (!nextCommand) {
        setTerminalError("修复命令为空，无法发送");
        return false;
      }
      await startTerminalSession();
      const ready = await waitForTerminalInputReady();
      if (!ready) {
        setTerminalError("终端尚未就绪，无法发送修复命令");
        return false;
      }
      return queueTerminalInput(`${nextCommand}\n`);
    },
    [queueTerminalInput, startTerminalSession, waitForTerminalInputReady]
  );

  const submitConnect = useCallback(async () => {
    setConnectBusy(true);
    setFormError("");
    try {
      const payload = {
        host: form.host.trim(),
        port: Number(form.port || 22),
        user: form.user.trim(),
        password: form.password,
        use_key: form.use_key,
        key_file: form.key_file.trim(),
        timeout_sec: Number(form.timeout_sec || 5),
      };
      await persistSettings();
      const data = await requestLocalApiJson("POST", "/api/v1/ssh/connect", { body: payload });
      setStatus((data?.item || null) as SSHStatus | null);
      setForm((current) => ({ ...current, password: "" }));
      setDialogOpen(false);
      router.push("/connect");
    } catch (error) {
      setFormError(normalizeFetchError(error) || "连接失败");
      return;
    } finally {
      setConnectBusy(false);
    }
  }, [form, persistSettings, router]);

  const submitDisconnect = useCallback(async () => {
    setDisconnectBusy(true);
    setFormError("");
    try {
      const data = await requestLocalApiJson("POST", "/api/v1/ssh/disconnect");
      const next = (data?.item || null) as SSHStatus | null;
      setStatus(next);
      setForm(toForm(next));
      setTerminalConnected(false);
      setTerminalInputEnabled(false);
      if (terminalOpen) {
        setTerminalMessage("SSH 已断开，终端会话已结束");
      }
      router.push("/");
    } catch (error) {
      setFormError(normalizeFetchError(error) || "断开失败");
      return;
    } finally {
      setDisconnectBusy(false);
    }
  }, [router, terminalOpen]);

  const value = useMemo<SshShellContextValue>(
    () => ({
      status,
      loading,
      dialogOpen,
      setDialogOpen,
      form,
      setForm,
      connectBusy,
      disconnectBusy,
      formError,
      clearFormError: () => setFormError(""),
      submitConnect,
      submitDisconnect,
    }),
    [status, loading, dialogOpen, form, connectBusy, disconnectBusy, formError, submitConnect, submitDisconnect]
  );

  const beginTerminalResize = (event: ReactPointerEvent<HTMLButtonElement>) => {
    dragStateRef.current = {
      startY: event.clientY,
      startHeight: terminalHeight,
    };
    document.body.classList.add("ssh-terminal-resizing");
  };

  return (
    <SshShellContext.Provider value={value}>
      <div className="min-h-screen bg-[#fbfbfa] text-slate-900">
        <div className="grid min-h-screen grid-cols-1 md:grid-cols-[240px_minmax(0,1fr)]">
          <aside className="border-b border-slate-200 bg-[#f7f7f5] md:border-b-0 md:border-r">
            <div className="flex h-full flex-col gap-2 p-3">
              <nav className="flex flex-col gap-1">
                <div
                  className={cn(
                    "group flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700",
                    pathname === "/connect" && "bg-slate-300 text-slate-950"
                  )}
                >
                  <button
                    type="button"
                    className={cn(
                      "flex min-w-0 flex-1 items-center gap-2 rounded-lg px-0 py-0 text-left text-sm transition-colors",
                      status?.connected ? "text-slate-900" : "text-slate-700"
                    )}
                    onClick={() => void (async () => {
                      if (!status?.connected) {
                        router.push("/connect");
                        setFormError("");
                        setForm(toForm(status));
                        setDialogOpen(true);
                        return;
                      }
                      const checkedStatus = await detectRuntimeReadiness();
                      if (checkedStatus === "missing") {
                        setPrepareDialogOpen(true);
                        return;
                      }
                      if (
                        checkedStatus === "unknown" &&
                        resolvedRuntimeState?.hostKey === runtimeIdentityKey &&
                        resolvedRuntimeState?.verificationStatus === "verified"
                      ) {
                        router.push("/connect");
                        return;
                      }
                      if (checkedStatus !== "ready") {
                        setPrepareDialogOpen(true);
                        return;
                      }
                      router.push("/connect");
                    })()}
                  >
                    <Link2 className={cn("h-4 w-4 shrink-0", status?.connected ? "text-blue-600" : "text-slate-500")} />
                    <span>连接</span>
                  </button>

                  {status?.connected ? (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button
                          type="button"
                          className="invisible rounded-md p-1 text-slate-400 transition hover:bg-slate-200/70 hover:text-slate-700 group-hover:visible"
                          aria-label="连接菜单"
                        >
                          <Ellipsis className="h-4 w-4" />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          onSelect={() => {
                            setPrepareDialogOpen(true);
                          }}
                        >
                          运行时设置
                        </DropdownMenuItem>
                        <DropdownMenuItem destructive onSelect={() => void submitDisconnect()}>
                          {disconnectBusy ? "断开中..." : "断开连接"}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  ) : null}
                </div>
              </nav>
            </div>
          </aside>

          <main className="min-h-screen min-w-0 bg-white p-0">
            <div className="flex h-full min-h-screen min-w-0 flex-col overflow-hidden bg-white">
              <div className="flex items-center justify-end gap-2 px-6 py-4">
                <button
                  type="button"
                  aria-label="远程终端"
                  title={status?.connected ? "远程终端" : "请先连接远端服务器"}
                  disabled={!status?.connected}
                  onClick={() => void (terminalOpen ? closeTerminalPanel() : startTerminalSession())}
                  className={cn(
                            "inline-flex h-10 w-10 items-center justify-center rounded-xl border text-slate-500 transition",
                            status?.connected
                              ? terminalOpen
                                ? "border-slate-200 bg-slate-100/90 shadow-sm text-slate-900"
                                : "border-transparent bg-transparent shadow-none hover:bg-slate-100/80 hover:text-slate-900"
                      : "cursor-not-allowed border-transparent bg-transparent opacity-40"
                  )}
                >
                  <TerminalIcon className="h-4 w-4" />
                </button>
              </div>

              <div className="flex min-h-0 flex-1 flex-col">
                <div className="min-h-0 flex-1 overflow-auto">
                  <div className="flex min-h-full w-full flex-col px-8 py-8">
                    {children}
                  </div>
                </div>

                {terminalOpen ? (
                  <>
                    <div className="relative h-px bg-slate-200">
                      <button
                        type="button"
                        aria-label="调整终端高度"
                        onPointerDown={beginTerminalResize}
                        className="absolute inset-x-0 -top-2 inline-flex h-4 w-full cursor-row-resize items-center justify-center text-slate-300 transition hover:text-slate-500"
                      >
                        <span className="bg-white px-2">
                          <GripHorizontal className="h-4 w-4" />
                        </span>
                      </button>
                    </div>

                    <section
                      className="border-t border-slate-200 bg-white"
                      style={{ height: `${terminalHeight}px` }}
                      aria-label="远程终端 · 当前服务器"
                    >
                      <div className="flex h-full flex-col">
                        <div className="flex items-center justify-between border-b border-slate-200 bg-white px-3 py-2">
                          <div className="min-w-0">
                            <p className="text-xs font-medium text-slate-600">终端</p>
                            <p className="truncate text-[11px] text-slate-400">
                              {status?.connected
                                ? `${status.user}@${status.host}:${status.port}`
                                : terminalMessage || "SSH 已断开，终端会话已结束"}
                            </p>
                          </div>
                          <div className="flex items-center gap-3">
                            <span className="text-[11px] font-mono text-slate-400">{terminalGridLabel}</span>
                            <button
                              type="button"
                              aria-label="关闭终端"
                              onClick={() => void closeTerminalPanel()}
                              className="rounded-md p-1 text-slate-400 transition hover:bg-white hover:text-slate-700"
                            >
                              <X className="h-4 w-4" />
                            </button>
                          </div>
                        </div>

                        {terminalError ? (
                          <div className="border-b border-red-100 bg-red-50 px-4 py-2 text-sm text-red-600">{terminalError}</div>
                        ) : null}

                        <div
                          ref={terminalSurfaceRef}
                          className="relative flex-1 overflow-hidden bg-white"
                        >
                          <div
                            ref={terminalViewportRef}
                            className={cn(
                              "ssh-terminal h-full w-full",
                              terminalInputEnabled ? "cursor-text" : "cursor-not-allowed opacity-90"
                            )}
                          />
                          {!terminalInputEnabled ? (
                            <div className="absolute inset-0 bg-white/55" aria-hidden="true" />
                          ) : null}
                        </div>
                      </div>
                    </section>
                  </>
                ) : null}
              </div>
            </div>
          </main>
        </div>
      </div>

      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open);
          if (!open && !(status?.connected)) {
            router.push("/");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>SSH 连接</DialogTitle>
            <DialogDescription>输入服务器信息后建立连接。</DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            {formError ? (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">{formError}</div>
            ) : null}

            <div className="grid gap-2">
              <Label htmlFor="ssh-host">主机地址</Label>
              <Input id="ssh-host" value={form.host} onChange={(e) => updateField("host", e.target.value)} />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label htmlFor="ssh-port">端口</Label>
                <Input id="ssh-port" value={form.port} onChange={(e) => updateField("port", e.target.value)} />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ssh-user">用户名</Label>
                <Input id="ssh-user" value={form.user} onChange={(e) => updateField("user", e.target.value)} />
              </div>
            </div>

            {form.use_key ? (
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500">
                已切换到密钥认证模式，密码输入已停用。
              </div>
            ) : (
              <div className="grid gap-2">
                <Label htmlFor="ssh-password">密码</Label>
                <Input id="ssh-password" type="password" value={form.password} onChange={(e) => updateField("password", e.target.value)} />
              </div>
            )}

            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={form.use_key}
                onChange={(e) => {
                  setFormError("");
                  setForm((current) => ({
                    ...current,
                    use_key: e.target.checked,
                    password: e.target.checked ? "" : current.password,
                  }));
                }}
                className="h-4 w-4 rounded border-slate-300"
              />
              <span>使用密钥文件</span>
            </label>

            {form.use_key ? (
              <div className="grid gap-2">
                <Label htmlFor="ssh-key-file">密钥文件</Label>
                <div className="flex gap-2">
                  <Input
                    id="ssh-key-file"
                    value={form.key_file}
                    readOnly
                    placeholder="请选择 SSH 密钥文件"
                    className="flex-1 cursor-default bg-slate-50"
                  />
                  <Button type="button" variant="outline" onClick={() => void selectKeyFile()}>
                    选择文件
                  </Button>
                </div>
              </div>
            ) : null}
          </div>

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
              取消
            </Button>
            <Button onClick={() => void submitConnect()} disabled={connectDisabled}>
              {connectBusy ? "连接中..." : "连接"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <PrepareServerWizard
        open={prepareDialogOpen}
        sshStatus={
          status?.connected
            ? {
                connected: status.connected,
                host: status.host,
                port: status.port,
                user: status.user,
              }
            : null
        }
        runtimeReady={runtimeStatus === "ready"}
        resolvedRuntime={resolvedRuntimeState}
        onOpenChange={setPrepareDialogOpen}
        onPrepared={(resolved) => {
          setRuntimeStatus("ready");
          setResolvedRuntimeState({
            hostKey: runtimeIdentityKey,
            nextflowPath: resolved?.nextflowPath || "",
            javaPath: resolved?.javaPath || "",
            selectedProfile: resolved?.selectedProfile || "",
            verificationStatus: "verified",
          });
          void fetchStatus({ silent: true });
        }}
        onOpenTerminal={() => void startTerminalSession()}
        onSendTerminalCommand={(command) => sendTerminalCommand(command)}
      />
    </SshShellContext.Provider>
  );
}

export function useSshShell() {
  const context = useContext(SshShellContext);
  if (!context) {
    throw new Error("useSshShell must be used within SshShellProvider");
  }
  return context;
}
