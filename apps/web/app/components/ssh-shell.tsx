"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { usePathname, useRouter } from "next/navigation";
import { CommandLineIcon, EllipsisHorizontalIcon, LinkIcon, XMarkIcon } from "@heroicons/react/24/outline";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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

type SshShellContextValue = {
  status: SSHStatus | null;
  loading: boolean;
  dialogOpen: boolean;
  setDialogOpen: (open: boolean) => void;
  connectLabelActive: boolean;
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

const SshShellContext = createContext<SshShellContextValue | null>(null);

function apiBase(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8765";
  return raw.trim().replace(/\/+$/, "");
}

async function readJsonOrThrow(resp: Response) {
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = typeof payload?.detail === "string" ? payload.detail : "";
    throw new Error(detail || `HTTP ${resp.status}`);
  }
  return payload;
}

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
  const message = error instanceof Error ? error.message : String(error || "");
  if (message.includes("Failed to fetch") || message.includes("NetworkError") || message.includes("Load failed")) {
    return `本地 API 未启动或不可达：${apiBase()}`;
  }
  return message || "请求失败";
}

export function SshShellProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const terminalViewportRef = useRef<HTMLPreElement | null>(null);
  const terminalCursorRef = useRef(0);
  const [status, setStatus] = useState<SSHStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<SSHFormState>(defaultForm);
  const [connectBusy, setConnectBusy] = useState(false);
  const [disconnectBusy, setDisconnectBusy] = useState(false);
  const [formError, setFormError] = useState("");
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [terminalSessionId, setTerminalSessionId] = useState<string | null>(null);
  const [terminalOutput, setTerminalOutput] = useState("");
  const [terminalMessage, setTerminalMessage] = useState("");
  const [terminalConnected, setTerminalConnected] = useState(false);
  const [terminalInputEnabled, setTerminalInputEnabled] = useState(false);
  const [terminalBusy, setTerminalBusy] = useState(false);
  const [terminalError, setTerminalError] = useState("");
  const [terminalCommand, setTerminalCommand] = useState("");

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
    setTerminalCommand("");
  }, []);

  const fetchStatus = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!options?.silent) {
        setLoading(true);
      }
      try {
        const resp = await fetch(`${apiBase()}/api/v1/ssh/status`, { cache: "no-store" });
        const data = await readJsonOrThrow(resp);
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
    void fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void fetchStatus({ silent: true });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [fetchStatus]);

  useEffect(() => {
    if (!terminalOpen) {
      return;
    }
    const node = terminalViewportRef.current;
    if (!node) {
      return;
    }
    node.scrollTop = node.scrollHeight;
  }, [terminalOpen, terminalOutput]);

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
    const resp = await fetch(`${apiBase()}/api/v1/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    await readJsonOrThrow(resp);
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

  const closeTerminalDrawer = useCallback(async () => {
    const activeSessionId = terminalSessionId;
    setTerminalOpen(false);
    resetTerminalState();
    if (!activeSessionId) {
      return;
    }
    try {
      await fetch(`${apiBase()}/api/v1/ssh/terminal/sessions/${activeSessionId}`, { method: "DELETE" });
    } catch {
      // ignore cleanup failures; local state is already cleared
    }
  }, [resetTerminalState, terminalSessionId]);

  const startTerminalSession = useCallback(
    async (options?: { replaceExisting?: boolean }) => {
      if (!status?.connected) {
        setTerminalOpen(true);
        setTerminalError("请先连接远端服务器");
        setTerminalInputEnabled(false);
        setTerminalConnected(false);
        return;
      }
      if (terminalOpen && terminalSessionId && terminalInputEnabled && !options?.replaceExisting) {
        return;
      }
      setTerminalOpen(true);
      setTerminalBusy(true);
      setTerminalError("");
      try {
        if (terminalSessionId) {
          await fetch(`${apiBase()}/api/v1/ssh/terminal/sessions/${terminalSessionId}`, { method: "DELETE" }).catch(() => undefined);
          resetTerminalState();
        }
        const resp = await fetch(`${apiBase()}/api/v1/ssh/terminal/sessions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ cols: 120, rows: 28 }),
        });
        const data = await readJsonOrThrow(resp);
        applyTerminalSnapshot((data?.item || null) as TerminalSnapshot, "replace");
      } catch (error) {
        setTerminalInputEnabled(false);
        setTerminalConnected(false);
        setTerminalError(normalizeFetchError(error) || "远程终端创建失败");
      } finally {
        setTerminalBusy(false);
      }
    },
    [applyTerminalSnapshot, resetTerminalState, status?.connected, terminalInputEnabled, terminalOpen, terminalSessionId]
  );

  useEffect(() => {
    if (!terminalOpen || !terminalSessionId) {
      return;
    }
    let cancelled = false;
    let timer: number | null = null;

    const poll = async () => {
      try {
        const resp = await fetch(
          `${apiBase()}/api/v1/ssh/terminal/sessions/${terminalSessionId}?cursor=${terminalCursorRef.current}`,
          { cache: "no-store" }
        );
        const data = await readJsonOrThrow(resp);
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
          timer = window.setTimeout(poll, 800);
        }
      }
    };

    timer = window.setTimeout(poll, 150);
    return () => {
      cancelled = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [applyTerminalSnapshot, fetchStatus, terminalOpen, terminalSessionId]);

  const connectDisabled =
    connectBusy ||
    !form.host.trim() ||
    !form.user.trim() ||
    (form.use_key ? !form.key_file.trim() : !form.password);

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
      const resp = await fetch(`${apiBase()}/api/v1/ssh/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await readJsonOrThrow(resp);
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
      const resp = await fetch(`${apiBase()}/api/v1/ssh/disconnect`, { method: "POST" });
      const data = await readJsonOrThrow(resp);
      const next = (data?.item || null) as SSHStatus | null;
      setStatus(next);
      setForm(toForm(next));
      setTerminalConnected(false);
      setTerminalInputEnabled(false);
      setTerminalMessage("SSH 已断开，终端会话已结束");
      router.push("/");
    } catch (error) {
      setFormError(normalizeFetchError(error) || "断开失败");
      return;
    } finally {
      setDisconnectBusy(false);
    }
  }, [router]);

  const submitTerminalCommand = useCallback(async () => {
    if (!terminalSessionId || !terminalInputEnabled || terminalBusy) {
      return;
    }
    const nextCommand = terminalCommand.trim();
    if (!nextCommand) {
      return;
    }
    setTerminalBusy(true);
    setTerminalError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/ssh/terminal/sessions/${terminalSessionId}/input`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data: `${nextCommand}\n` }),
      });
      await readJsonOrThrow(resp);
      setTerminalCommand("");
    } catch (error) {
      setTerminalError(normalizeFetchError(error) || "终端输入发送失败");
    } finally {
      setTerminalBusy(false);
    }
  }, [terminalBusy, terminalCommand, terminalInputEnabled, terminalSessionId]);

  const value = useMemo<SshShellContextValue>(
    () => ({
      status,
      loading,
      dialogOpen,
      setDialogOpen,
      connectLabelActive: pathname === "/connect",
      form,
      setForm,
      connectBusy,
      disconnectBusy,
      formError,
      clearFormError: () => setFormError(""),
      submitConnect,
      submitDisconnect,
    }),
    [status, loading, dialogOpen, pathname, form, connectBusy, disconnectBusy, formError, submitConnect, submitDisconnect]
  );

  const terminalActionDisabled = loading || terminalBusy || !status?.connected;
  const terminalStatusLabel = terminalInputEnabled ? "远端会话已连接" : status?.connected ? "等待重新创建会话" : "SSH 已断开";

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
                      router.push("/connect");
                      setFormError("");
                      setForm(toForm(status));
                      if (!status?.connected) {
                        setDialogOpen(true);
                      }
                    }}
                  >
                    <LinkIcon className={cn("h-4 w-4 shrink-0", status?.connected ? "text-blue-600" : "text-slate-500")} />
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
                          <EllipsisHorizontalIcon className="h-4 w-4" />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
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

          <main className={cn("min-w-0 p-4 md:p-6 lg:p-8", terminalOpen && "pb-[25rem] md:pb-[27rem]")}>
            <div className="mb-4 flex justify-end">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={terminalActionDisabled}
                title={status?.connected ? "打开远程终端" : "请先连接远端服务器"}
                className="gap-2"
                onClick={() => void startTerminalSession()}
              >
                <CommandLineIcon className="h-4 w-4" />
                <span>{terminalBusy ? "启动终端..." : "远程终端"}</span>
              </Button>
            </div>
            {children}
          </main>
        </div>
      </div>

      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open);
          if (!open && !status?.connected) {
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
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              取消
            </Button>
            <Button onClick={() => void submitConnect()} disabled={connectDisabled}>
              {connectBusy ? "连接中..." : "连接"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {terminalOpen ? (
        <div className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex justify-center px-4 pb-4 md:px-6">
          <div className="pointer-events-auto flex h-[22rem] w-full max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 shadow-2xl md:h-[24rem]">
            <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3 text-slate-100">
              <div>
                <div className="text-sm font-semibold">远程终端 · 当前服务器</div>
                <div className="mt-1 text-xs text-slate-400">{terminalStatusLabel}</div>
              </div>
              <div className="flex items-center gap-2">
                {status?.connected && !terminalInputEnabled ? (
                  <Button type="button" variant="outline" size="sm" className="border-slate-700 bg-slate-900 text-slate-100 hover:bg-slate-800" onClick={() => void startTerminalSession({ replaceExisting: true })}>
                    新建会话
                  </Button>
                ) : null}
                <button
                  type="button"
                  onClick={() => void closeTerminalDrawer()}
                  className="rounded-md p-1 text-slate-400 transition hover:bg-slate-800 hover:text-slate-100"
                  aria-label="关闭远程终端"
                >
                  <XMarkIcon className="h-5 w-5" />
                </button>
              </div>
            </div>

            {(!status?.connected || (terminalSessionId !== null && !terminalInputEnabled)) ? (
              <div className="border-b border-amber-700/40 bg-amber-500/10 px-4 py-2 text-sm text-amber-100">
                SSH 已断开，终端会话已结束
              </div>
            ) : null}
            {terminalError ? (
              <div className="border-b border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-200">{terminalError}</div>
            ) : null}

            <div className="flex min-h-0 flex-1 flex-col">
              <pre
                ref={terminalViewportRef}
                className="min-h-0 flex-1 overflow-auto bg-slate-950 px-4 py-3 font-mono text-[13px] leading-6 text-slate-100 whitespace-pre-wrap break-words"
              >
                {terminalOutput || "终端已就绪，输入命令后将在这里显示远端输出。"}
              </pre>

              <form
                className="border-t border-slate-800 bg-slate-900 px-4 py-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  void submitTerminalCommand();
                }}
              >
                <div className="flex flex-col gap-2 md:flex-row">
                  <Input
                    value={terminalCommand}
                    onChange={(event) => setTerminalCommand(event.target.value)}
                    placeholder={terminalInputEnabled ? "输入命令并回车，例如 pwd / whoami / echo hello" : "SSH 已断开，请重新建立会话"}
                    disabled={!terminalInputEnabled || terminalBusy}
                    className="border-slate-700 bg-slate-950 text-slate-100 placeholder:text-slate-500"
                  />
                  <Button
                    type="submit"
                    disabled={!terminalInputEnabled || terminalBusy || !terminalCommand.trim()}
                    className="md:min-w-24"
                  >
                    {terminalBusy ? "发送中..." : "发送"}
                  </Button>
                </div>
                <div className="mt-2 text-xs text-slate-400">{terminalMessage || "v1 仅提供纯远程终端能力，不包含本地终端与快捷动作。"}</div>
              </form>
            </div>
          </div>
        </div>
      ) : null}
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
