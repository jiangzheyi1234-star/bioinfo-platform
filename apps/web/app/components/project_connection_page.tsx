"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { open } from "@tauri-apps/plugin-dialog";
import {
  ArrowPathIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  Cog6ToothIcon,
  ServerStackIcon,
  WrenchScrewdriverIcon,
  CircleStackIcon,
} from "@heroicons/react/24/outline";

import type {
  DatabaseEntry,
  InstallJobSnapshot,
  PreflightResult,
  RemoteEnvStatus,
  SSHDiagnosticStep,
  SSHSettings,
  SSHStatus,
  SettingsPayload,
} from "./detection_workspace_types";
import {
  apiBase,
  isRecord,
  defaultSSHSettings,
  parseInstallJobSnapshot,
  parsePreflightResult,
  parseRemoteEnvStatus,
  parseSettingsPayload,
  parseSSHDiagnosticSteps,
  parseSSHSettings,
  parseSSHStatus,
  readJsonOrThrow,
  safeText,
  toDatabaseEntry,
} from "./detection_workspace_utils";
import { useWorkspaceShell } from "./workspace_shell_context";

type SectionKey = "preflight" | "env" | "databases";

function formatStatusLabel(status: string): string {
  if (status === "installed") return "已安装";
  if (status === "installing" || status === "running") return "安装中";
  if (status === "failed") return "失败";
  if (status === "blocked") return "阻塞";
  if (status === "ready") return "已就绪";
  if (status === "incomplete") return "不完整";
  if (status === "not_installed") return "未安装";
  if (status === "unknown") return "未知";
  return status || "未知";
}

function sectionTone(status: string): "ok" | "warn" | "fail" {
  if (status === "ready" || status === "installed") {
    return "ok";
  }
  if (status === "failed" || status === "not_installed" || status === "blocked") {
    return "fail";
  }
  return "warn";
}

export function ProjectConnectionPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { currentProjectId, setShellError } = useWorkspaceShell();

  const [settingsPayload, setSettingsPayload] = useState<SettingsPayload>({});
  const [sshSettings, setSSHSettings] = useState<SSHSettings>(defaultSSHSettings());
  const [sshStatus, setSSHStatus] = useState<SSHStatus | null>(null);
  const [sshDiagnostics, setSSHDiagnostics] = useState<SSHDiagnosticStep[]>([]);
  const [sshBusyAction, setSSHBusyAction] = useState("");
  const [sshMessage, setSSHMessage] = useState("");
  const [isEditingConnection, setIsEditingConnection] = useState(false);
  const [editRequestConsumed, setEditRequestConsumed] = useState(false);

  const [sectionsOpen, setSectionsOpen] = useState<Record<SectionKey, boolean>>({
    preflight: true,
    env: true,
    databases: true,
  });

  const [preflight, setPreflight] = useState<PreflightResult | null>(null);
  const [preflightBusy, setPreflightBusy] = useState(false);
  const [preflightError, setPreflightError] = useState("");

  const [envStatus, setEnvStatus] = useState<RemoteEnvStatus | null>(null);
  const [envBusy, setEnvBusy] = useState(false);
  const [envError, setEnvError] = useState("");
  const [envInstallBusyKey, setEnvInstallBusyKey] = useState("");
  const [openEnvLogs, setOpenEnvLogs] = useState<Record<string, boolean>>({});
  const [envJobSnapshots, setEnvJobSnapshots] = useState<Record<string, InstallJobSnapshot>>({});

  const [databases, setDatabases] = useState<DatabaseEntry[]>([]);
  const [dbBusy, setDbBusy] = useState(false);
  const [dbError, setDbError] = useState("");
  const [dbInstallBusyId, setDbInstallBusyId] = useState("");
  const [dbSaveBusyId, setDbSaveBusyId] = useState("");
  const [dbPathDrafts, setDbPathDrafts] = useState<Record<string, string>>({});
  const [dbPathEditors, setDbPathEditors] = useState<Record<string, boolean>>({});
  const [openDbLogs, setOpenDbLogs] = useState<Record<string, boolean>>({});
  const [dbJobSnapshots, setDbJobSnapshots] = useState<Record<string, InstallJobSnapshot>>({});

  const isConnected = sshStatus?.connected === true;
  const canEditForm = !isConnected || isEditingConnection;
  const buttonsLocked = sshBusyAction.length > 0 || (isConnected && !isEditingConnection);

  const updateSSHField = <K extends keyof SSHSettings>(key: K, value: SSHSettings[K]) => {
    setSSHSettings((prev) => ({ ...prev, [key]: value }));
  };

  const syncFromServer = async () => {
    const [settingsResp, statusResp] = await Promise.all([
      fetch(`${apiBase()}/api/v1/settings`),
      fetch(`${apiBase()}/api/v1/ssh/status`),
    ]);
    const settingsData = await readJsonOrThrow(settingsResp);
    const statusData = await readJsonOrThrow(statusResp);
    const payload = parseSettingsPayload(settingsData?.item);
    setSettingsPayload(payload);
    setSSHSettings(parseSSHSettings(payload.ssh));
    const nextStatus = parseSSHStatus(statusData?.item);
    setSSHStatus(nextStatus);
    if (nextStatus?.connected) {
      setIsEditingConnection(false);
    }
  };

  const refreshPreflight = async () => {
    if (!isConnected) {
      setPreflight(null);
      setPreflightError("");
      return;
    }
    setPreflightBusy(true);
    setPreflightError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/ssh/preflight`, { method: "POST" });
      const data = await readJsonOrThrow(resp);
      setPreflight(parsePreflightResult(data?.item));
    } catch (err) {
      setPreflightError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreflightBusy(false);
    }
  };

  const refreshEnvStatus = async () => {
    if (!isConnected) {
      setEnvStatus(null);
      setEnvError("");
      return;
    }
    setEnvBusy(true);
    setEnvError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/ssh/env/status`);
      const data = await readJsonOrThrow(resp);
      setEnvStatus(parseRemoteEnvStatus(data?.item));
    } catch (err) {
      setEnvError(err instanceof Error ? err.message : String(err));
    } finally {
      setEnvBusy(false);
    }
  };

  const refreshDatabases = async () => {
    if (!currentProjectId) {
      setDatabases([]);
      setDbError("");
      return;
    }
    if (!isConnected) {
      setDatabases([]);
      setDbError("");
      return;
    }
    setDbBusy(true);
    setDbError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/databases?include_status=true`);
      const data = (await readJsonOrThrow(resp)) as { items?: unknown[] };
      const items = Array.isArray(data.items)
        ? data.items.map(toDatabaseEntry).filter((item: DatabaseEntry | null): item is DatabaseEntry => !!item)
        : [];
      setDatabases(items);
      setDbPathDrafts((prev) => {
        const next = { ...prev };
        for (const item of items) {
          if (!(item.db_id in next)) {
            next[item.db_id] = item.configured_override || item.resolved_path || "";
          }
        }
        return next;
      });
    } catch (err) {
      setDbError(err instanceof Error ? err.message : String(err));
    } finally {
      setDbBusy(false);
    }
  };

  const refreshRemoteConsole = async () => {
    if (!isConnected) {
      return;
    }
    await Promise.all([refreshPreflight(), refreshEnvStatus(), refreshDatabases()]);
  };

  const persistSSHSettings = async () => {
    const resp = await fetch(`${apiBase()}/api/v1/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        patch: {
          ssh: {
            host: sshSettings.host,
            port: sshSettings.port,
            user: sshSettings.user,
            password: sshSettings.password,
            use_key: sshSettings.use_key,
            key_file: sshSettings.key_file,
          },
        },
      }),
    });
    const data = await readJsonOrThrow(resp);
    const payload = parseSettingsPayload(data?.item);
    setSettingsPayload(payload);
    setSSHSettings(parseSSHSettings(payload.ssh));
  };

  const connectSSH = async () => {
    if (isConnected && !isEditingConnection) {
      setShellError("SSH 已连接；如需修改连接，请先进入编辑模式。");
      return;
    }
    setShellError("");
    setSSHMessage("");
    setSSHBusyAction("connect");
    try {
      await persistSSHSettings();
      const resp = await fetch(`${apiBase()}/api/v1/ssh/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(sshSettings),
      });
      const data = await readJsonOrThrow(resp);
      setSSHStatus(parseSSHStatus(data?.item));
      setSSHDiagnostics([]);
      setSSHMessage(safeText(data?.item?.message, "SSH 已连接"));
      setIsEditingConnection(false);
      await refreshRemoteConsole();
    } catch (err) {
      setShellError(err instanceof Error ? err.message : String(err));
    } finally {
      setSSHBusyAction("");
    }
  };

  const startConnectionEdit = async () => {
    setShellError("");
    setSSHMessage("");
    setSSHBusyAction("disconnect");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/ssh/disconnect`, { method: "POST" });
      const data = await readJsonOrThrow(resp);
      setSSHStatus(parseSSHStatus(data?.item));
      setIsEditingConnection(true);
      setPreflight(null);
      setEnvStatus(null);
      setDatabases([]);
      setSSHMessage("");
    } catch (err) {
      setShellError(err instanceof Error ? err.message : String(err));
    } finally {
      setSSHBusyAction("");
    }
  };

  const testSSH = async () => {
    setShellError("");
    setSSHMessage("");
    setSSHBusyAction("test");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/ssh/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(sshSettings),
      });
      const data = await readJsonOrThrow(resp);
      setSSHDiagnostics(parseSSHDiagnosticSteps(data?.item?.steps));
      setSSHStatus(parseSSHStatus(data?.item?.status));
      setSSHMessage(safeText(data?.item?.message));
    } catch (err) {
      setShellError(err instanceof Error ? err.message : String(err));
    } finally {
      setSSHBusyAction("");
    }
  };

  const browseKeyFile = async () => {
    setShellError("");
    try {
      const selected = await open({
        directory: false,
        multiple: false,
        title: "选择 SSH 私钥文件",
        filters: [
          { name: "SSH Key", extensions: ["pem", "key", "rsa", "ppk"] },
          { name: "All Files", extensions: ["*"] },
        ],
      });
      if (typeof selected === "string" && selected.trim()) {
        updateSSHField("key_file", selected);
      }
    } catch (err) {
      setShellError(err instanceof Error ? err.message : String(err));
    }
  };

  const refreshEnvJob = async (jobId: string) => {
    const normalized = safeText(jobId);
    if (!normalized) {
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/ssh/env/install/${encodeURIComponent(normalized)}`);
    const data = await readJsonOrThrow(resp);
    const snapshot = parseInstallJobSnapshot(data?.item);
    if (snapshot) {
      setEnvJobSnapshots((prev) => ({ ...prev, [normalized]: snapshot }));
    }
  };

  const refreshDatabaseJob = async (dbId: string) => {
    if (!currentProjectId) {
      return;
    }
    const normalized = safeText(dbId);
    if (!normalized) {
      return;
    }
    const resp = await fetch(
      `${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/databases/${encodeURIComponent(normalized)}/install`
    );
    const data = await readJsonOrThrow(resp);
    const snapshot = parseInstallJobSnapshot(data?.item);
    if (snapshot) {
      setDbJobSnapshots((prev) => ({ ...prev, [normalized]: snapshot }));
    }
  };

  const installEnv = async (target: "miniforge" | "tool_env", toolId = "") => {
    const busyKey = target === "miniforge" ? "miniforge" : toolId;
    setEnvInstallBusyKey(busyKey);
    setShellError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/ssh/env/install`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target, tool_id: toolId || undefined }),
      });
      const data = await readJsonOrThrow(resp);
      const jobId = safeText(data?.item?.job_id);
      if (jobId) {
        await refreshEnvJob(jobId);
      }
      await refreshEnvStatus();
    } catch (err) {
      setShellError(err instanceof Error ? err.message : String(err));
    } finally {
      setEnvInstallBusyKey("");
    }
  };

  const installDatabase = async (dbId: string) => {
    if (!currentProjectId) {
      setShellError("请先选择项目。");
      return;
    }
    setDbInstallBusyId(dbId);
    setShellError("");
    try {
      const resp = await fetch(
        `${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/databases/${encodeURIComponent(dbId)}/install`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mirror_index: 0 }),
        }
      );
      await readJsonOrThrow(resp);
      await refreshDatabaseJob(dbId);
      await refreshDatabases();
    } catch (err) {
      setShellError(err instanceof Error ? err.message : String(err));
    } finally {
      setDbInstallBusyId("");
    }
  };

  const saveDatabaseOverride = async (dbId: string) => {
    const draft = safeText(dbPathDrafts[dbId]).trim();
    const databasesCfg = isRecord(settingsPayload["databases"]) ? settingsPayload["databases"] : {};
    const currentOverrides = isRecord(databasesCfg["overrides"]) ? databasesCfg["overrides"] : {};
    const nextOverrides: Record<string, string> = {};
    for (const [key, value] of Object.entries(currentOverrides)) {
      const normalized = safeText(value).trim();
      if (normalized) {
        nextOverrides[key] = normalized;
      }
    }
    if (draft) {
      nextOverrides[dbId] = draft;
    } else {
      delete nextOverrides[dbId];
    }

    setDbSaveBusyId(dbId);
    setShellError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          patch: {
            databases: {
              overrides: nextOverrides,
            },
          },
        }),
      });
      const data = await readJsonOrThrow(resp);
      setSettingsPayload(parseSettingsPayload(data?.item));
      setDbPathEditors((prev) => ({ ...prev, [dbId]: false }));
      await refreshDatabases();
    } catch (err) {
      setShellError(err instanceof Error ? err.message : String(err));
    } finally {
      setDbSaveBusyId("");
    }
  };

  useEffect(() => {
    void (async () => {
      try {
        await syncFromServer();
      } catch (err) {
        setShellError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [setShellError]);

  useEffect(() => {
    if (!isConnected) {
      return;
    }
    void refreshRemoteConsole();
  }, [isConnected, currentProjectId]);

  useEffect(() => {
    if (searchParams.get("edit") !== "1" || editRequestConsumed || !sshStatus?.connected || isEditingConnection || sshBusyAction) {
      return;
    }
    setEditRequestConsumed(true);
    void startConnectionEdit();
  }, [editRequestConsumed, isEditingConnection, searchParams, sshBusyAction, sshStatus?.connected]);

  useEffect(() => {
    if (!isConnected) {
      return;
    }
    const envJobs = new Set<string>();
    if (envStatus?.miniforge?.job_id && envStatus.miniforge.status === "running") {
      envJobs.add(envStatus.miniforge.job_id);
    }
    for (const row of envStatus?.tool_envs || []) {
      if (row.status === "installing" && row.job_id) {
        envJobs.add(row.job_id);
      }
    }
    const dbIds = databases.filter((row) => row.status === "installing" || row.install_stage === "running").map((row) => row.db_id);
    if (envJobs.size === 0 && dbIds.length === 0) {
      return;
    }
    const timer = window.setInterval(() => {
      void refreshEnvStatus();
      void refreshDatabases();
      for (const jobId of envJobs) {
        if (openEnvLogs[jobId]) {
          void refreshEnvJob(jobId);
        }
      }
      for (const dbId of dbIds) {
        if (openDbLogs[dbId]) {
          void refreshDatabaseJob(dbId);
        }
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [isConnected, envStatus, databases, openEnvLogs, openDbLogs, currentProjectId]);

  const connectedSummary = sshStatus?.connected ? `${sshStatus.user}@${sshStatus.host}:${sshStatus.port}` : "未连接";
  const settingsDatabases = isRecord(settingsPayload["databases"]) ? settingsPayload["databases"] : {};
  const currentOverrides = isRecord(settingsDatabases["overrides"]) ? settingsDatabases["overrides"] : {};

  return (
    <section className="settings-layout">
      <section className="settings-column connection-console-column">
        <section className="settings-editor-panel connection-panel">
          <div className="connection-status-row">
            <span className={`status-pill${sshStatus?.connected ? " status-pill--ok" : ""}`}>{sshStatus?.connected ? "已连接" : "未连接"}</span>
            <span className="muted">{sshMessage || connectedSummary}</span>
          </div>

          {isConnected && !isEditingConnection ? (
            <div className="connection-summary-bar">
              <div className="connection-summary-main">
                <strong>远端连接</strong>
                <span className="muted">{connectedSummary}</span>
              </div>
              <div className="connection-summary-actions">
                <button className="ui-button" type="button" disabled={sshBusyAction === "disconnect"} onClick={() => void startConnectionEdit()}>
                  {sshBusyAction === "disconnect" ? "断开中..." : "断开 / 编辑"}
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="settings-form-grid">
                <div className="field-block">
                  <label className="field-label" htmlFor="ssh-host">
                    Host
                  </label>
                  <input id="ssh-host" className="control-input" value={sshSettings.host} onChange={(event) => updateSSHField("host", event.target.value)} placeholder="192.168.0.152" disabled={!canEditForm} />
                </div>
                <div className="field-block">
                  <label className="field-label" htmlFor="ssh-port">
                    Port
                  </label>
                  <input id="ssh-port" className="control-input" type="number" value={sshSettings.port} onChange={(event) => updateSSHField("port", Number(event.target.value || 22))} placeholder="22" disabled={!canEditForm} />
                </div>
                <div className="field-block">
                  <label className="field-label" htmlFor="ssh-user">
                    User
                  </label>
                  <input id="ssh-user" className="control-input" value={sshSettings.user} onChange={(event) => updateSSHField("user", event.target.value)} placeholder="ubuntu" disabled={!canEditForm} />
                </div>
                <div className="field-block">
                  <label className="field-label" htmlFor="ssh-password">
                    Password
                  </label>
                  <input id="ssh-password" className="control-input" type="password" value={sshSettings.password} onChange={(event) => updateSSHField("password", event.target.value)} placeholder={sshSettings.use_key ? "密钥模式下可留空" : "输入 SSH 密码"} disabled={!canEditForm} />
                </div>
                <div className="field-block field-block--full">
                  <label className="field-label" htmlFor="ssh-key-file">
                    Key File
                  </label>
                  <div className="file-picker-row">
                    <input id="ssh-key-file" className="control-input file-picker-input" value={sshSettings.key_file} placeholder="选择 SSH 私钥文件" readOnly disabled={!canEditForm} />
                    <button className="control-btn" type="button" disabled={!canEditForm} onClick={() => void browseKeyFile()}>
                      浏览
                    </button>
                  </div>
                </div>
                <label className="checkbox-row field-block--full" htmlFor="ssh-use-key">
                  <input id="ssh-use-key" type="checkbox" checked={sshSettings.use_key} onChange={(event) => updateSSHField("use_key", event.target.checked)} disabled={!canEditForm} />
                  <span>使用密钥连接</span>
                </label>
              </div>

              <div className="settings-actions connection-actions">
                <button className="ui-button" disabled={buttonsLocked} onClick={() => void testSSH()}>
                  {sshBusyAction === "test" ? "测试中..." : "测试"}
                </button>
                <button className="ui-button ui-button--primary" disabled={buttonsLocked} onClick={() => void connectSSH()}>
                  {sshBusyAction === "connect" ? "连接中..." : "连接"}
                </button>
              </div>
            </>
          )}

          {sshDiagnostics.length > 0 ? (
            <div className="diagnostics-list connection-diagnostics">
              {sshDiagnostics.map((step) => (
                <article key={step.name} className={`diagnostic-card diagnostic-card--${step.status}`}>
                  <div className="row">
                    <strong>{step.name}</strong>
                    <span className="badge">{step.status}</span>
                  </div>
                  <p className="muted">{step.message || "无额外信息"}</p>
                </article>
              ))}
            </div>
          ) : null}
        </section>

        {isConnected ? (
          <section className="connection-console-stack">
            <section className="settings-editor-panel connection-console-panel">
              <div className="connection-console-header">
                <div className="connection-console-header-main">
                  <ServerStackIcon className="connection-console-header-icon" />
                  <div>
                    <h3>服务器预检</h3>
                    <p className="muted">{preflight?.ok ? "这台服务器已经满足基础安装条件" : "确认远端架构、下载能力和后台任务能力"}</p>
                  </div>
                </div>
                <div className="connection-console-header-actions">
                  <button className="ui-button" type="button" disabled={preflightBusy} onClick={(event) => { event.stopPropagation(); void refreshPreflight(); }}>
                    <ArrowPathIcon className="connection-console-action-icon" />
                    {preflightBusy ? "检测中..." : "重新检测"}
                  </button>
                  <button className="connection-console-toggle" type="button" onClick={() => setSectionsOpen((prev) => ({ ...prev, preflight: !prev.preflight }))}>
                    {sectionsOpen.preflight ? <ChevronDownIcon className="connection-console-chevron" /> : <ChevronRightIcon className="connection-console-chevron" />}
                  </button>
                </div>
              </div>

              {sectionsOpen.preflight ? (
                <div className="connection-console-body">
                  {preflightError ? <div className="connection-console-error">{preflightError}</div> : null}
                  {!preflight && !preflightBusy ? <div className="muted">尚未获取预检结果。</div> : null}
                  {preflight ? (
                    <>
                      {preflight.failures.length > 0 ? (
                        <div className="connection-console-warning">
                          <strong>预检发现阻塞项</strong>
                          <div className="muted">{preflight.failures.join("；")}</div>
                        </div>
                      ) : null}
                      <div className="connection-card-grid">
                        {preflight.checks.map((item) => (
                          <article key={item.key} className={`diagnostic-card diagnostic-card--${item.status === "warn" ? "fail" : item.status}`}>
                            <div className="row">
                              <strong>{item.label}</strong>
                              <span className="badge">{item.value}</span>
                            </div>
                            <p className="muted">{item.message}</p>
                          </article>
                        ))}
                      </div>
                    </>
                  ) : null}
                </div>
              ) : null}
            </section>

            <section className="settings-editor-panel connection-console-panel">
              <div className="connection-console-header">
                <div className="connection-console-header-main">
                  <WrenchScrewdriverIcon className="connection-console-header-icon" />
                  <div>
                    <h3>运行环境</h3>
                    <p className="muted">Miniforge 与工具 conda 环境统一在这里查看和安装。</p>
                  </div>
                </div>
                <div className="connection-console-header-actions">
                  <span className="badge">{envStatus?.summary.installed ?? 0} / {envStatus?.summary.total ?? 0}</span>
                  <button className="ui-button" type="button" disabled={envBusy} onClick={(event) => { event.stopPropagation(); void refreshEnvStatus(); }}>
                    <ArrowPathIcon className="connection-console-action-icon" />
                    {envBusy ? "刷新中..." : "刷新"}
                  </button>
                  <button className="connection-console-toggle" type="button" onClick={() => setSectionsOpen((prev) => ({ ...prev, env: !prev.env }))}>
                    {sectionsOpen.env ? <ChevronDownIcon className="connection-console-chevron" /> : <ChevronRightIcon className="connection-console-chevron" />}
                  </button>
                </div>
              </div>

              {sectionsOpen.env ? (
                <div className="connection-console-body">
                  {envError ? <div className="connection-console-error">{envError}</div> : null}
                  {envStatus ? (
                    <>
                      <article className={`connection-resource-row tone-${sectionTone(envStatus.miniforge.status)}`}>
                        <div className="connection-resource-main">
                          <div className="connection-resource-title-row">
                            <strong>Miniforge</strong>
                            <span className={`badge badge-tone-${sectionTone(envStatus.miniforge.status)}`}>{formatStatusLabel(envStatus.miniforge.status)}</span>
                            {envStatus.miniforge.version ? <span className="badge">v{envStatus.miniforge.version}</span> : null}
                          </div>
                          <div className="muted">{envStatus.miniforge.message || "远端自管 conda"}</div>
                          {envStatus.miniforge.conda_executable ? <div className="connection-resource-path">{envStatus.miniforge.conda_executable}</div> : null}
                        </div>
                        <div className="connection-resource-actions">
                          <button className="ui-button ui-button--primary" type="button" disabled={envInstallBusyKey === "miniforge" || envStatus.miniforge.status === "running"} onClick={() => void installEnv("miniforge")}>
                            {envInstallBusyKey === "miniforge" || envStatus.miniforge.status === "running" ? "安装中..." : envStatus.miniforge.installed ? "重装" : "安装"}
                          </button>
                          <button className="ui-button" type="button" onClick={() => {
                            setOpenEnvLogs((prev) => ({ ...prev, [envStatus.miniforge.job_id]: !prev[envStatus.miniforge.job_id] }));
                            void refreshEnvJob(envStatus.miniforge.job_id);
                          }}>
                            {openEnvLogs[envStatus.miniforge.job_id] ? "收起日志" : "日志"}
                          </button>
                        </div>
                      </article>

                      {openEnvLogs[envStatus.miniforge.job_id] ? (
                        <pre className="connection-log-box">{envJobSnapshots[envStatus.miniforge.job_id]?.log_text || envStatus.miniforge.log_text || "暂无日志"}</pre>
                      ) : null}

                      <div className="connection-resource-list">
                        {envStatus.tool_envs.map((row) => {
                          const snapshot = envJobSnapshots[row.job_id];
                          const miniforgeReady = envStatus.miniforge.installed;
                          return (
                            <div key={row.tool_id} className={`connection-resource-row tone-${sectionTone(row.status)}`}>
                              <div className="connection-resource-main">
                                <div className="connection-resource-title-row">
                                  <strong>{row.name}</strong>
                                  <span className={`badge badge-tone-${sectionTone(row.status)}`}>{formatStatusLabel(row.status)}</span>
                                  <span className="badge">{row.env_name}</span>
                                  {row.version ? <span className="badge">v{row.version}</span> : null}
                                </div>
                                <div className="muted">{row.message || "未提供状态说明"}</div>
                                {row.shared_tool_ids.length > 1 ? <div className="connection-resource-path">共享工具: {row.shared_tool_ids.join(", ")}</div> : null}
                              </div>
                              <div className="connection-resource-actions">
                                <button
                                  className="ui-button ui-button--primary"
                                  type="button"
                                  disabled={!row.installable || !miniforgeReady || envInstallBusyKey === row.tool_id || row.status === "installing"}
                                  onClick={() => void installEnv("tool_env", row.tool_id)}
                                >
                                  {envInstallBusyKey === row.tool_id || row.status === "installing" ? "安装中..." : row.installed ? "重装" : "安装"}
                                </button>
                                <button
                                  className="ui-button"
                                  type="button"
                                  disabled={!row.job_id}
                                  onClick={() => {
                                    setOpenEnvLogs((prev) => ({ ...prev, [row.job_id]: !prev[row.job_id] }));
                                    if (row.job_id) {
                                      void refreshEnvJob(row.job_id);
                                    }
                                  }}
                                >
                                  {openEnvLogs[row.job_id] ? "收起日志" : "日志"}
                                </button>
                              </div>
                              {openEnvLogs[row.job_id] ? (
                                <pre className="connection-log-box connection-log-box--inline">
                                  {snapshot?.log_text || row.log_text || "暂无日志"}
                                </pre>
                              ) : null}
                            </div>
                          );
                        })}
                      </div>
                    </>
                  ) : (
                    <div className="muted">尚未获取环境状态。</div>
                  )}
                </div>
              ) : null}
            </section>

            <section className="settings-editor-panel connection-console-panel">
              <div className="connection-console-header">
                <div className="connection-console-header-main">
                  <CircleStackIcon className="connection-console-header-icon" />
                  <div>
                    <h3>数据库依赖</h3>
                    <p className="muted">为当前项目维护数据库路径，并在远端验证或安装数据库。</p>
                  </div>
                </div>
                <div className="connection-console-header-actions">
                  {currentProjectId ? <span className="badge">{databases.length}</span> : <span className="badge">no project</span>}
                  <button className="ui-button" type="button" onClick={(event) => { event.stopPropagation(); router.push("/settings"); }}>
                    <Cog6ToothIcon className="connection-console-action-icon" />
                    前往设置
                  </button>
                  <button className="connection-console-toggle" type="button" onClick={() => setSectionsOpen((prev) => ({ ...prev, databases: !prev.databases }))}>
                    {sectionsOpen.databases ? <ChevronDownIcon className="connection-console-chevron" /> : <ChevronRightIcon className="connection-console-chevron" />}
                  </button>
                </div>
              </div>

              {sectionsOpen.databases ? (
                <div className="connection-console-body">
                  {!currentProjectId ? <div className="muted">当前未打开项目，数据库依赖区块暂不可用。</div> : null}
                  {dbError ? <div className="connection-console-error">{dbError}</div> : null}
                  {currentProjectId && databases.length === 0 && !dbBusy ? <div className="muted">未发现数据库条目。</div> : null}
                  <div className="connection-resource-list">
                    {databases.map((db) => {
                      const draftValue = dbPathDrafts[db.db_id] ?? db.configured_override ?? db.resolved_path;
                      const snapshot = dbJobSnapshots[db.db_id];
                      const logOpen = openDbLogs[db.db_id];
                      return (
                        <div key={db.db_id} className={`connection-resource-row tone-${sectionTone(db.status || "unknown")}`}>
                          <div className="connection-resource-main">
                            <div className="connection-resource-title-row">
                              <strong>{db.name}</strong>
                              <span className={`badge badge-tone-${sectionTone(db.status || "unknown")}`}>{formatStatusLabel(db.status || "unknown")}</span>
                              <span className="badge">{db.db_id}</span>
                            </div>
                            <div className="muted">{db.description || db.status_message || "未提供数据库说明"}</div>
                            <div className="connection-resource-path">{db.resolved_path || "(未配置路径)"}</div>
                            {db.status_message ? <div className="muted">{db.status_message}</div> : null}
                            {dbPathEditors[db.db_id] ? (
                              <div className="connection-inline-editor">
                                <input
                                  className="control-input"
                                  value={draftValue}
                                  onChange={(event) => setDbPathDrafts((prev) => ({ ...prev, [db.db_id]: event.target.value }))}
                                  placeholder="输入绝对路径；留空可移除 override"
                                />
                                <button className="ui-button ui-button--primary" type="button" disabled={dbSaveBusyId === db.db_id} onClick={() => void saveDatabaseOverride(db.db_id)}>
                                  {dbSaveBusyId === db.db_id ? "保存中..." : "保存"}
                                </button>
                                <button className="ui-button" type="button" onClick={() => setDbPathEditors((prev) => ({ ...prev, [db.db_id]: false }))}>
                                  取消
                                </button>
                              </div>
                            ) : null}
                          </div>
                          <div className="connection-resource-actions">
                            <button className="ui-button" type="button" onClick={() => setDbPathEditors((prev) => ({ ...prev, [db.db_id]: !prev[db.db_id] }))}>
                              {dbPathEditors[db.db_id] ? "收起路径" : "配置路径"}
                            </button>
                            <button
                              className="ui-button ui-button--primary"
                              type="button"
                              disabled={!db.installable || dbInstallBusyId === db.db_id || db.status === "installing" || !envStatus?.miniforge.installed}
                              onClick={() => void installDatabase(db.db_id)}
                            >
                              {dbInstallBusyId === db.db_id || db.status === "installing" ? "安装中..." : "安装"}
                            </button>
                            <button
                              className="ui-button"
                              type="button"
                              disabled={!db.install_job_id}
                              onClick={() => {
                                setOpenDbLogs((prev) => ({ ...prev, [db.db_id]: !prev[db.db_id] }));
                                void refreshDatabaseJob(db.db_id);
                              }}
                            >
                              {logOpen ? "收起日志" : "日志"}
                            </button>
                          </div>
                          {logOpen ? <pre className="connection-log-box connection-log-box--inline">{snapshot?.log_text || "暂无安装日志"}</pre> : null}
                        </div>
                      );
                    })}
                  </div>
                  {isRecord(currentOverrides) && Object.keys(currentOverrides).length > 0 ? (
                    <div className="muted connection-inline-note">当前已配置 overrides: {Object.keys(currentOverrides).join(", ")}</div>
                  ) : null}
                </div>
              ) : null}
            </section>
          </section>
        ) : null}
      </section>
    </section>
  );
}
