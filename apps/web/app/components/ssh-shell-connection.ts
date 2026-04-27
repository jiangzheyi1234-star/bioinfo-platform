"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";

import { requestLocalApiJson } from "@/app/lib/local-api-client";

import {
  type SSHFormState,
  type SSHStatus,
  type SshShellContextValue,
  defaultForm,
  normalizeFetchError,
  toForm,
} from "./ssh-shell-model";

function canAutoConnectOnStartup(form: SSHFormState): boolean {
  return form.remember_auth;
}

export type UseSshConnectionResult = {
  contextValue: SshShellContextValue;
  status: SSHStatus | null;
  form: SSHFormState;
  formError: string;
  successNotice: string;
  connectBusy: boolean;
  disconnectBusy: boolean;
  ensureRunnerBusy: boolean;
  connectDisabled: boolean;
  updateField: <K extends keyof SSHFormState>(key: K, value: SSHFormState[K]) => void;
  selectKeyFile: () => Promise<void>;
  refreshStatus: (options?: { silent?: boolean }) => Promise<SSHStatus | null>;
  ensureRunner: () => Promise<void>;
};

function makePreparingStatus(form: SSHFormState): SSHStatus {
  return {
    configured: true,
    connected: true,
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
    runner: {
      state: "preparing",
      ready: false,
      message: "Connecting SSH...",
      reasonCode: "",
    },
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
  const [formError, setFormError] = useState("");
  const [successNotice, setSuccessNotice] = useState("");
  const ensureInFlightRef = useRef(false);

  const refreshStatus = useCallback(
    async (options?: { silent?: boolean }): Promise<SSHStatus | null> => {
      if (!options?.silent) {
        setLoading(true);
      }
      try {
        const data = await requestLocalApiJson("GET", "/api/v1/ssh/status", { cache: "no-store" });
        const next = (data?.item || null) as SSHStatus | null;
        setStatus(next);
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
      } catch {
        setStatus(null);
        return null;
      } finally {
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
    }, 5000);
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
      const servers = await requestLocalApiJson("GET", "/api/v1/servers", { cache: "no-store" });
      const serverId = servers?.data?.items?.[0]?.serverId;
      if (!serverId) {
        return;
      }
      const ensured = await requestLocalApiJson("POST", `/api/v1/servers/${serverId}/ensure-runner`);
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
    const previousStatus = status;
    setStatus(makePreparingStatus(form));
    setDialogOpen(false);
    try {
      const autoConnectOnStartup = canAutoConnectOnStartup(form) ? form.auto_connect_on_startup : false;
      const payload = {
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
      const data = await requestLocalApiJson("POST", "/api/v1/ssh/connect", { body: payload });
      setStatus((data?.item || null) as SSHStatus | null);
      setForm((current) => ({ ...current, password: "" }));
      const targetLabel = form.auth_mode === "ssh_config" ? form.ssh_host_alias.trim() || form.host.trim() : form.host.trim();
      setSuccessNotice(
        form.remember_auth
          ? autoConnectOnStartup
            ? `已保存 ${targetLabel} 的连接方式，下次启动会自动连接。`
            : `已保存 ${targetLabel} 的连接方式，下次可直接使用。`
          : `已连接到 ${targetLabel}，本次不会保存为下次默认连接。`
      );
    } catch (error) {
      setStatus(previousStatus);
      setDialogOpen(true);
      setFormError(normalizeFetchError(error) || "连接失败");
    } finally {
      setConnectBusy(false);
    }
  }, [form, status]);

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
    connectBusy,
    disconnectBusy,
    ensureRunnerBusy,
    connectDisabled,
    updateField,
    selectKeyFile,
    refreshStatus,
    ensureRunner,
  };
}
