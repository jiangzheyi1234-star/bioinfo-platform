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

type XTermLike = {
  open: (element: HTMLElement) => void;
  write: (data: string) => void;
  reset: () => void;
  focus: () => void;
  dispose: () => void;
  loadAddon: (addon: FitAddonLike) => void;
  onData: (handler: (data: string) => void) => TerminalDisposable;
  cols?: number;
  rows?: number;
  options: {
    disableStdin?: boolean;
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
const DEFAULT_TERMINAL_HEIGHT = 220;
const MIN_TERMINAL_HEIGHT = 160;
const MAX_TERMINAL_HEIGHT = 420;

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

function clampTerminalHeight(value: number): number {
  return Math.max(MIN_TERMINAL_HEIGHT, Math.min(MAX_TERMINAL_HEIGHT, Math.round(value)));
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

export function SshShellProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const terminalViewportRef = useRef<HTMLDivElement | null>(null);
  const terminalHandleRef = useRef<TerminalHandle | null>(null);
  const renderedTerminalOutputRef = useRef("");
  const creatingTerminalSessionRef = useRef(false);
  const terminalInputChainRef = useRef(Promise.resolve());
  const terminalCursorRef = useRef(0);
  const dragStateRef = useRef<{ startY: number; startHeight: number } | null>(null);

  const [status, setStatus] = useState<SSHStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [prepareDialogOpen, setPrepareDialogOpen] = useState(false);
  const [form, setForm] = useState<SSHFormState>(defaultForm);
  const [connectBusy, setConnectBusy] = useState(false);
  const [disconnectBusy, setDisconnectBusy] = useState(false);
  const [formError, setFormError] = useState("");
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus>("unknown");

  const [terminalOpen, setTerminalOpen] = useState(false);
  const [terminalHeight, setTerminalHeight] = useState(DEFAULT_TERMINAL_HEIGHT);
  const [terminalSessionId, setTerminalSessionId] = useState<string | null>(null);
  const [terminalOutput, setTerminalOutput] = useState("");
  const [terminalMessage, setTerminalMessage] = useState("");
  const [terminalConnected, setTerminalConnected] = useState(false);
  const [terminalInputEnabled, setTerminalInputEnabled] = useState(false);
  const [terminalBusy, setTerminalBusy] = useState(false);
  const [terminalError, setTerminalError] = useState("");

  const applyTerminalSnapshot = useCallback((item: TerminalSnapshot, mode: "replace" | "append" = "append") => {
    terminalCursorRef.current = item.cursor || 0;
    setTerminalSessionId(item.session_id);
    setTerminalMessage(item.message || "");
    setTerminalConnected(Boolean(item.connected));
    setTerminalInputEnabled(Boolean(item.input_enabled));
    setTerminalOutput((current) => {
      const nextChunk = typeof item.output === "string" ? item.output : "";
      return mode === "replace" ? nextChunk : `${current}${nextChunk}`;
    });
  }, []);

  const resetTerminalState = useCallback(() => {
    terminalCursorRef.current = 0;
    setTerminalSessionId(null);
    setTerminalOutput("");
    setTerminalMessage("");
    setTerminalConnected(false);
    setTerminalInputEnabled(false);
    setTerminalBusy(false);
    setTerminalError("");
    terminalInputChainRef.current = Promise.resolve();
  }, []);

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
    setTerminalHeight(readStoredTerminalHeight());
    void fetchStatus();
  }, [fetchStatus]);

  const detectRuntimeReadiness = useCallback(async () => {
    if (!status?.connected) {
      setRuntimeStatus("unknown");
      return;
    }
    try {
      const inspection = await loadRuntimeInspection();
      setRuntimeStatus(deriveRuntimeStatus(inspection));
    } catch {
      setRuntimeStatus("unknown");
    }
  }, [status?.connected]);

  useEffect(() => {
    if (!status?.connected) {
      setRuntimeStatus("unknown");
      return;
    }
    void detectRuntimeReadiness();
  }, [detectRuntimeReadiness, status?.connected]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void fetchStatus({ silent: true });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [fetchStatus]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(TERMINAL_HEIGHT_KEY, String(terminalHeight));
    }
  }, [terminalHeight]);

  useEffect(() => {
    if (status?.connected || !terminalOpen) {
      return;
    }
    setTerminalConnected(false);
    setTerminalInputEnabled(false);
    setTerminalMessage("SSH 已断开，终端会话已结束");
  }, [status?.connected, terminalOpen]);

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

  const queueTerminalInput = useCallback(
    (data: string) => {
      if (!data) {
        return;
      }
      if (!terminalSessionId) {
        setTerminalError("终端会话尚未建立");
        return;
      }
      if (!terminalInputEnabled) {
        setTerminalError(terminalMessage || "SSH 已断开，终端会话已结束");
        return;
      }

      const sessionId = terminalSessionId;
      terminalInputChainRef.current = terminalInputChainRef.current
        .catch(() => undefined)
        .then(async () => {
          await requestLocalApiJson("POST", `/api/v1/ssh/terminal/sessions/${sessionId}/input`, {
            body: { data },
          });
        })
        .catch((error: unknown) => {
          setTerminalError(normalizeFetchError(error) || "发送终端输入失败");
        });
    },
    [terminalInputEnabled, terminalMessage, terminalSessionId]
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
        fontFamily:
          '"JetBrains Mono", "SFMono-Regular", ui-monospace, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
        fontSize: 13,
        lineHeight: 1.4,
        scrollback: 4000,
        theme: {
          background: "#ffffff",
          foreground: "#334155",
          cursor: "#64748b",
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
        },
      }) as unknown as XTermLike;
      const fitAddon = new FitAddon();
      terminal.loadAddon(fitAddon);
      terminal.open(node);
      fitAddon.fit();
      terminalHandleRef.current = { terminal, fitAddon };
      renderedTerminalOutputRef.current = "";

      const inputDisposable = terminal.onData((data) => {
        queueTerminalInput(data);
      });
      const focusTimer = window.setTimeout(() => terminal.focus(), 0);
      const handleWindowResize = () => fitAddon.fit();
      window.addEventListener("resize", handleWindowResize);

      cleanup = () => {
        window.clearTimeout(focusTimer);
        inputDisposable.dispose();
        window.removeEventListener("resize", handleWindowResize);
        terminalHandleRef.current = null;
        renderedTerminalOutputRef.current = "";
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
  }, [queueTerminalInput, terminalOpen]);

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
    if (!terminalOpen) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      terminalHandleRef.current?.fitAddon.fit();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [terminalHeight, terminalOpen]);

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
    creatingTerminalSessionRef.current = false;
    setTerminalOpen(false);
    resetTerminalState();
    if (!activeSessionId) {
      return;
    }
    try {
      await requestLocalApiJson("DELETE", `/api/v1/ssh/terminal/sessions/${activeSessionId}`);
    } catch {
      // ignore cleanup failures; local state is already cleared
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
      creatingTerminalSessionRef.current = true;
      setTerminalBusy(true);
      try {
        if (!terminalHandleRef.current) {
          await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
        }
        const dimensions = terminalHandleRef.current?.terminal;
        const cols = Math.max(80, dimensions?.cols || 120);
        const rows = Math.max(20, dimensions?.rows || 28);
        if (terminalSessionId) {
          await requestLocalApiJson("DELETE", `/api/v1/ssh/terminal/sessions/${terminalSessionId}`).catch(() => undefined);
          resetTerminalState();
        }
        const data = await requestLocalApiJson("POST", "/api/v1/ssh/terminal/sessions", {
          body: { cols, rows },
        });
        applyTerminalSnapshot((data?.item || null) as TerminalSnapshot, "replace");
      } catch (error) {
        setTerminalInputEnabled(false);
        setTerminalConnected(false);
        setTerminalError(normalizeFetchError(error) || "远程终端创建失败");
      } finally {
        creatingTerminalSessionRef.current = false;
        setTerminalBusy(false);
      }
    },
    [applyTerminalSnapshot, resetTerminalState, status?.connected, terminalInputEnabled, terminalSessionId]
  );

  useEffect(() => {
    if (!terminalOpen || !terminalSessionId) {
      return;
    }
    let cancelled = false;
    let timer: number | null = null;

    const poll = async () => {
      try {
        const data = await requestLocalApiJson(
          "GET",
          `/api/v1/ssh/terminal/sessions/${terminalSessionId}?cursor=${terminalCursorRef.current}`,
          { cache: "no-store" }
        );
        if (cancelled) {
          return;
        }
        applyTerminalSnapshot((data?.item || null) as TerminalSnapshot, "append");
        setTerminalError("");
        void fetchStatus({ silent: true });
      } catch (error) {
        if (cancelled) {
          return;
        }
        setTerminalInputEnabled(false);
        setTerminalConnected(false);
        setTerminalError(normalizeFetchError(error) || "终端输出读取失败");
      } finally {
        if (!cancelled) {
          timer = window.setTimeout(poll, 250);
        }
      }
    };

    timer = window.setTimeout(poll, 100);
    return () => {
      cancelled = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [applyTerminalSnapshot, fetchStatus, terminalOpen, terminalSessionId]);

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
                    onClick={() => {
                      if (!status?.connected) {
                        router.push("/connect");
                        setFormError("");
                        setForm(toForm(status));
                        setDialogOpen(true);
                        return;
                      }
                      if (runtimeStatus !== "ready") {
                        setPrepareDialogOpen(true);
                        return;
                      }
                      router.push("/connect");
                    }}
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
                  <div className="mx-auto flex min-h-full w-full max-w-6xl flex-col px-8 py-8">
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
                      className="bg-white"
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
                          <button
                            type="button"
                            aria-label="关闭终端"
                            onClick={() => void closeTerminalPanel()}
                            className="rounded-md p-1 text-slate-400 transition hover:bg-white hover:text-slate-700"
                          >
                            <X className="h-4 w-4" />
                          </button>
                        </div>

                        {terminalError ? (
                          <div className="border-b border-red-100 bg-red-50 px-4 py-2 text-sm text-red-600">{terminalError}</div>
                        ) : null}

                        <div className="relative flex-1 overflow-hidden bg-white">
                          {!terminalSessionId && terminalBusy ? (
                            <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center text-sm text-slate-400">
                              正在建立远程终端会话…
                            </div>
                          ) : null}
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
        onOpenChange={setPrepareDialogOpen}
        onPrepared={() => {
          setRuntimeStatus("ready");
          void fetchStatus({ silent: true });
        }}
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
