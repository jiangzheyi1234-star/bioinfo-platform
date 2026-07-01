"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";

import { LocalApiError, requestLocalApiJson } from "@/app/lib/local-api-client";

import {
  type SSHHostKeyCandidate,
  type SSHFormState,
  type SSHStatus,
  type SshShellContextValue,
  defaultForm,
  normalizeFetchError,
  runnerRequiresExplicitStart,
  toForm,
} from "./ssh-shell-model";

const SSH_CONNECT_REQUEST_TIMEOUT_BUFFER_MS = 5_000;
const SSH_CONNECT_REQUEST_TIMEOUT_MAX_MS = 30_000;
const ENSURE_RUNNER_REQUEST_TIMEOUT_MS = 180_000;

function sshConnectRequestTimeoutMs(timeoutSec: string): number {
  const configured = Number(timeoutSec || 5);
  const boundedSeconds = Number.isFinite(configured) ? Math.max(1, configured) : 5;
  return Math.min(SSH_CONNECT_REQUEST_TIMEOUT_MAX_MS, boundedSeconds * 1000 + SSH_CONNECT_REQUEST_TIMEOUT_BUFFER_MS);
}

function canAutoConnectOnStartup(form: SSHFormState): boolean {
  return form.remember_auth;
}

function buildSshConnectionPayload(form: SSHFormState) {
  const autoConnectOnStartup = canAutoConnectOnStartup(form) ? form.auto_connect_on_startup : false;
  return {
    auth_mode: form.auth_mode,
    ssh_host_alias: form.auth_mode === "ssh_config" ? form.ssh_host_alias.trim() : "",
    identity_ref: form.auth_mode === "key_file" ? form.identity_ref.trim() : "",
    remember_auth: form.remember_auth,
    auto_connect_on_startup: autoConnectOnStartup,
    host: form.host.trim(),
    port: Number(form.port || 22),
    user: form.user.trim(),
    password: form.password,
    timeout_sec: Number(form.timeout_sec || 5),
  };
}

function buildSshHostKeyTargetPayload(form: SSHFormState) {
  return {
    auth_mode: form.auth_mode,
    ssh_host_alias: form.auth_mode === "ssh_config" ? form.ssh_host_alias.trim() : "",
    host: form.host.trim(),
    port: Number(form.port || 22),
    user: form.user.trim(),
    timeout_sec: Number(form.timeout_sec || 5),
  };
}

function targetLabelForForm(form: SSHFormState): string {
  return form.auth_mode === "ssh_config" ? form.ssh_host_alias.trim() || form.host.trim() : form.host.trim();
}

function isHostKeyTrustError(error: unknown): boolean {
  const parts = [
    error instanceof Error ? error.message : String(error || ""),
    error instanceof LocalApiError && typeof error.detail === "string" ? error.detail : "",
    error instanceof LocalApiError && error.problemCode ? error.problemCode : "",
  ];
  return parts.some((part) => part.includes("SSH_HOST_KEY_UNTRUSTED") || part.includes("主机密钥未受信任"));
}

function connectionSuccessMessage(form: SSHFormState): string {
  const targetLabel = targetLabelForForm(form);
  const autoConnectOnStartup = canAutoConnectOnStartup(form) ? form.auto_connect_on_startup : false;
  if (!form.remember_auth) {
    return `已连接到 ${targetLabel}，本次不会保存为下次默认连接。`;
  }
  return autoConnectOnStartup
    ? `已保存 ${targetLabel} 的连接方式，下次启动会自动连接。`
    : `已保存 ${targetLabel} 的连接方式，下次可直接使用。`;
}

export type UseSshConnectionResult = {
  contextValue: SshShellContextValue;
  status: SSHStatus | null;
  form: SSHFormState;
  formError: string;
  successNotice: string;
  hostKeyCandidate: SSHHostKeyCandidate | null;
  connectBusy: boolean;
  disconnectBusy: boolean;
  ensureRunnerBusy: boolean;
  hostKeyBusy: boolean;
  connectDisabled: boolean;
  updateField: <K extends keyof SSHFormState>(key: K, value: SSHFormState[K]) => void;
  selectKeyFile: () => Promise<void>;
  refreshStatus: (options?: { silent?: boolean }) => Promise<SSHStatus | null>;
  ensureRunner: () => Promise<void>;
  acceptHostKey: () => Promise<void>;
};

function makePreparingStatus(form: SSHFormState): SSHStatus {
  return {
    configured: true,
    connected: false,
    connecting: true,
    auth_mode: form.auth_mode,
    ssh_host_alias: form.auth_mode === "ssh_config" ? form.ssh_host_alias.trim() : "",
    identity_ref: form.auth_mode === "key_file" ? form.identity_ref.trim() : "",
    remember_auth: form.remember_auth,
    host: form.host.trim(),
    port: Number(form.port || 22),
    user: form.user.trim(),
    has_password: false,
    timeout_sec: Number(form.timeout_sec || 5),
    auto_connect_on_startup: canAutoConnectOnStartup(form) ? form.auto_connect_on_startup : false,
    message: "SSH connecting",
  };
}

export function useSshConnection(): UseSshConnectionResult {
  const [status, setStatus] = useState<SSHStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<SSHFormState>(defaultForm);
  const [connectBusy, setConnectBusy] = useState(false);
  const [disconnectBusy, setDisconnectBusy] = useState(false);
  const [ensureRunnerBusy, setEnsureRunnerBusy] = useState(false);
  const [hostKeyBusy, setHostKeyBusy] = useState(false);
  const [hostKeyCandidate, setHostKeyCandidate] = useState<SSHHostKeyCandidate | null>(null);
  const [formError, setFormError] = useState("");
  const [successNotice, setSuccessNotice] = useState("");
  const ensureInFlightRef = useRef(false);
  const statusInFlightRef = useRef<Promise<SSHStatus | null> | null>(null);
  const statusRef = useRef<SSHStatus | null>(null);
  const lastStatusRefreshRef = useRef(0);

  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  const refreshStatus = useCallback(
    async (options?: { silent?: boolean }): Promise<SSHStatus | null> => {
      if (options?.silent && Date.now() - lastStatusRefreshRef.current < 15_000) {
        return statusRef.current;
      }
      if (options?.silent && statusInFlightRef.current) {
        return statusInFlightRef.current;
      }
      if (!options?.silent) {
        setLoading(true);
      }
      const request = (async () => {
        const statusPath = options?.silent ? "/api/v1/ssh/status" : "/api/v1/ssh/status?refresh=true";
        const data = await requestLocalApiJson("GET", statusPath, { cache: "no-store" });
        const next = (data?.item || null) as SSHStatus | null;
        setStatus(next);
        lastStatusRefreshRef.current = Date.now();
        setForm((current) => {
          if (
            dialogOpen &&
            (current.host || current.user || current.password || current.identity_ref || current.ssh_host_alias)
          ) {
            return current;
          }
          setFormError("");
          return toForm(next);
        });
        return next;
      })();
      statusInFlightRef.current = request;
      try {
        return await request;
      } catch {
        setStatus(null);
        return null;
      } finally {
        if (statusInFlightRef.current === request) {
          statusInFlightRef.current = null;
        }
        if (!options?.silent) {
          setLoading(false);
        }
      }
    },
    [dialogOpen]
  );

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void refreshStatus({ silent: true });
    }, 30000);
    return () => window.clearInterval(timer);
  }, [refreshStatus]);

  const ensureRunner = useCallback(async () => {
    if (!status?.connected || ensureInFlightRef.current) {
      return;
    }
    ensureInFlightRef.current = true;
    setEnsureRunnerBusy(true);
    setStatus((current) =>
      current?.connected
        ? {
            ...current,
            runner: {
              state: "preparing",
              ready: false,
              message: "Checking remote runner...",
              reasonCode: "",
            },
          }
        : current
    );
    try {
      const servers = status.serverId ? null : await requestLocalApiJson("GET", "/api/v1/servers", { cache: "no-store" });
      const serverId = status.serverId || servers?.data?.items?.[0]?.serverId;
      if (!serverId) {
        return;
      }
      const actionPath = runnerRequiresExplicitStart(status) ? "runner/start" : "ensure-runner";
      const ensured = await requestLocalApiJson("POST", `/api/v1/servers/${encodeURIComponent(serverId)}/${actionPath}`, {
        timeoutMs: ENSURE_RUNNER_REQUEST_TIMEOUT_MS,
      });
      const runner = ensured?.data?.runner;
      if (runner) {
        setStatus((current) => (current?.connected ? { ...current, runner } : current));
      } else {
        await refreshStatus({ silent: true });
      }
    } catch (error) {
      setStatus((current) =>
        current?.connected
          ? {
              ...current,
              runner: {
                state: "repair_needed",
                ready: false,
                message: normalizeFetchError(error) || "Remote runner is not ready.",
                reasonCode: "RUNNER_NOT_READY",
              },
            }
          : current
      );
    } finally {
      ensureInFlightRef.current = false;
      setEnsureRunnerBusy(false);
    }
  }, [refreshStatus, status]);

  useEffect(() => {
    if (!status?.connected || status.runner || ensureInFlightRef.current) {
      return;
    }
    void ensureRunner();
  }, [ensureRunner, status]);

  useEffect(() => {
    if (!successNotice) {
      return;
    }
    const timer = window.setTimeout(() => {
      setSuccessNotice("");
    }, 5000);
    return () => window.clearTimeout(timer);
  }, [successNotice]);

  const selectKeyFile = useCallback(async () => {
    try {
      const selected = await open({
        multiple: false,
        directory: false,
        title: "选择 SSH 密钥文件",
      });
      if (typeof selected === "string" && selected.trim()) {
        setForm((current) => ({ ...current, auth_mode: "key_file", identity_ref: selected }));
      }
    } catch (error) {
      setFormError(error instanceof Error ? error.message : String(error || "选择密钥文件失败"));
    }
  }, []);

  const updateField = useCallback(<K extends keyof SSHFormState>(key: K, value: SSHFormState[K]) => {
    setFormError("");
    setHostKeyCandidate(null);
    setForm((current) => {
      if (key === "remember_auth") {
        const rememberAuth = value as boolean;
        return {
          ...current,
          remember_auth: rememberAuth,
          auto_connect_on_startup: rememberAuth ? current.auto_connect_on_startup : false,
        };
      }
      if (key === "auto_connect_on_startup") {
        return {
          ...current,
          auto_connect_on_startup: current.remember_auth && value === true,
        };
      }
      if (key !== "auth_mode") {
        return { ...current, [key]: value };
      }
      const authMode = value as SSHFormState["auth_mode"];
      return {
        ...current,
        auth_mode: authMode,
        password: authMode === "password_ref" ? current.password : "",
        ssh_host_alias: authMode === "ssh_config" ? current.ssh_host_alias : "",
        identity_ref: authMode === "key_file" ? current.identity_ref : "",
        auto_connect_on_startup: current.remember_auth ? current.auto_connect_on_startup : false,
      };
    });
  }, []);

  const submitConnect = useCallback(async () => {
    setConnectBusy(true);
    setFormError("");
    setSuccessNotice("");
    setHostKeyCandidate(null);
    const previousStatus = status;
    const payload = buildSshConnectionPayload(form);
    setStatus(makePreparingStatus(form));
    setDialogOpen(false);
    try {
      const data = await requestLocalApiJson("POST", "/api/v1/ssh/connect", {
        body: payload,
        timeoutMs: sshConnectRequestTimeoutMs(form.timeout_sec),
      });
      setStatus((data?.item || null) as SSHStatus | null);
      setForm((current) => ({ ...current, password: "" }));
      setSuccessNotice(connectionSuccessMessage(form));
    } catch (error) {
      setStatus(previousStatus);
      setDialogOpen(true);
      if (isHostKeyTrustError(error)) {
        try {
          const scanned = await requestLocalApiJson("POST", "/api/v1/ssh/host-key/scan", {
            body: buildSshHostKeyTargetPayload(form),
            timeoutMs: sshConnectRequestTimeoutMs(form.timeout_sec),
          });
          setHostKeyCandidate((scanned?.data || null) as SSHHostKeyCandidate | null);
          setFormError("SSH 主机密钥未受信任，请确认 fingerprint 后继续。");
        } catch (scanError) {
          setFormError(normalizeFetchError(scanError) || "SSH 主机密钥扫描失败");
        }
        return;
      }
      setFormError(normalizeFetchError(error) || "连接失败");
    } finally {
      setConnectBusy(false);
    }
  }, [form, status]);

  const acceptHostKey = useCallback(async () => {
    if (!hostKeyCandidate || hostKeyBusy) {
      return;
    }
    setHostKeyBusy(true);
    setFormError("");
    setSuccessNotice("");
    const payload = buildSshConnectionPayload(form);
    const hostKeyPayload = buildSshHostKeyTargetPayload(form);
    try {
      await requestLocalApiJson("POST", `/api/v1/servers/${encodeURIComponent(hostKeyCandidate.serverId)}/host-key/accept`, {
        body: {
          ...hostKeyPayload,
          confirmation: "trust-ssh-host-key",
          fingerprintSha256: hostKeyCandidate.hostKeyFingerprintSha256,
        },
        timeoutMs: sshConnectRequestTimeoutMs(form.timeout_sec),
      });
      const data = await requestLocalApiJson("POST", "/api/v1/ssh/connect", {
        body: payload,
        timeoutMs: sshConnectRequestTimeoutMs(form.timeout_sec),
      });
      setHostKeyCandidate(null);
      setStatus((data?.item || null) as SSHStatus | null);
      setForm((current) => ({ ...current, password: "" }));
      setDialogOpen(false);
      setSuccessNotice(connectionSuccessMessage(form));
    } catch (error) {
      setFormError(normalizeFetchError(error) || "SSH 主机密钥确认失败");
    } finally {
      setHostKeyBusy(false);
    }
  }, [form, hostKeyBusy, hostKeyCandidate]);

  const submitDisconnect = useCallback(async () => {
    setDisconnectBusy(true);
    setFormError("");
    try {
      const data = await requestLocalApiJson("POST", "/api/v1/ssh/disconnect");
      const next = (data?.item || null) as SSHStatus | null;
      setStatus(next);
      setForm(toForm(next));
    } catch (error) {
      setFormError(normalizeFetchError(error) || "断开失败");
    } finally {
      setDisconnectBusy(false);
    }
  }, []);

  const connectDisabled =
    connectBusy ||
    hostKeyBusy ||
    (form.auth_mode === "ssh_config"
      ? !form.ssh_host_alias.trim()
      : !form.host.trim() ||
        !form.user.trim() ||
        (form.auth_mode === "key_file" ? !form.identity_ref.trim() : form.auth_mode === "password_ref" ? !form.password : false));

  const contextValue = useMemo<SshShellContextValue>(
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

  return {
    contextValue,
    status,
    form,
    formError,
    successNotice,
    hostKeyCandidate,
    connectBusy,
    disconnectBusy,
    ensureRunnerBusy,
    hostKeyBusy,
    connectDisabled,
    updateField,
    selectKeyFile,
    refreshStatus,
    ensureRunner,
    acceptHostKey,
  };
}
