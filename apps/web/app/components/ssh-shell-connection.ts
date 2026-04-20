"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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

type RouterLike = {
  push: (href: string) => void;
};

export type UseSshConnectionResult = {
  contextValue: SshShellContextValue;
  status: SSHStatus | null;
  form: SSHFormState;
  formError: string;
  successNotice: string;
  connectBusy: boolean;
  disconnectBusy: boolean;
  connectDisabled: boolean;
  updateField: <K extends keyof SSHFormState>(key: K, value: SSHFormState[K]) => void;
  selectKeyFile: () => Promise<void>;
  refreshStatus: (options?: { silent?: boolean }) => Promise<SSHStatus | null>;
};

export function useSshConnection(router: RouterLike): UseSshConnectionResult {
  const [status, setStatus] = useState<SSHStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<SSHFormState>(defaultForm);
  const [connectBusy, setConnectBusy] = useState(false);
  const [disconnectBusy, setDisconnectBusy] = useState(false);
  const [formError, setFormError] = useState("");
  const [successNotice, setSuccessNotice] = useState("");

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

  useEffect(() => {
    if (!successNotice) {
      return;
    }
    const timer = window.setTimeout(() => {
      setSuccessNotice("");
    }, 5000);
    return () => window.clearTimeout(timer);
  }, [successNotice]);

  const persistSettings = useCallback(async () => {
    const payload = {
      patch: {
        ssh: {
          auth_mode: form.auth_mode,
          ssh_host_alias: form.auth_mode === "ssh_config" ? form.ssh_host_alias.trim() : "",
          identity_ref: form.auth_mode === "key_file" ? form.identity_ref.trim() : "",
          remember_auth: form.remember_auth,
          host: form.host.trim(),
          port: Number(form.port || 22),
          user: form.user.trim(),
          timeout_sec: Number(form.timeout_sec || 5),
          auto_connect_on_startup: form.remember_auth ? form.auto_connect_on_startup : false,
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
        setForm((current) => ({ ...current, auth_mode: "key_file", identity_ref: selected }));
      }
    } catch (error) {
      setFormError(error instanceof Error ? error.message : String(error || "选择密钥文件失败"));
    }
  }, []);

  const updateField = useCallback(<K extends keyof SSHFormState>(key: K, value: SSHFormState[K]) => {
    setFormError("");
    setForm((current) => {
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
        auto_connect_on_startup:
          authMode === "password_ref"
            ? false
            : current.remember_auth
              ? current.auto_connect_on_startup
              : false,
      };
    });
  }, []);

  const submitConnect = useCallback(async () => {
    setConnectBusy(true);
    setFormError("");
    try {
      const payload = {
        auth_mode: form.auth_mode,
        ssh_host_alias: form.auth_mode === "ssh_config" ? form.ssh_host_alias.trim() : "",
        identity_ref: form.auth_mode === "key_file" ? form.identity_ref.trim() : "",
        remember_auth: form.remember_auth,
        auto_connect_on_startup: form.remember_auth ? form.auto_connect_on_startup : false,
        host: form.host.trim(),
        port: Number(form.port || 22),
        user: form.user.trim(),
        password: form.password,
        timeout_sec: Number(form.timeout_sec || 5),
      };
      await persistSettings();
      const data = await requestLocalApiJson("POST", "/api/v1/ssh/connect", { body: payload });
      setStatus((data?.item || null) as SSHStatus | null);
      setForm((current) => ({ ...current, password: "" }));
      const targetLabel = form.auth_mode === "ssh_config" ? form.ssh_host_alias.trim() || form.host.trim() : form.host.trim();
      setSuccessNotice(
        form.remember_auth
          ? form.auto_connect_on_startup
            ? `已保存 ${targetLabel} 的连接方式，下次启动会自动连接。`
            : `已保存 ${targetLabel} 的连接方式，下次可直接使用。`
          : `已连接到 ${targetLabel}，本次不会保存为下次默认连接。`
      );
      setDialogOpen(false);
      router.push("/connect");
    } catch (error) {
      setFormError(normalizeFetchError(error) || "连接失败");
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
      router.push("/");
    } catch (error) {
      setFormError(normalizeFetchError(error) || "断开失败");
    } finally {
      setDisconnectBusy(false);
    }
  }, [router]);

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
    connectDisabled,
    updateField,
    selectKeyFile,
    refreshStatus,
  };
}
