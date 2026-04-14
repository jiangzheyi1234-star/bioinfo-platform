"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ChevronRightIcon } from "@heroicons/react/24/outline";
import { open } from "@tauri-apps/plugin-dialog";

import type { InstallJobSnapshot, PreflightResult, RemoteEnvStatus, SSHDiagnosticStep, SSHSettings, SSHStatus } from "./detection_workspace_types";
import {
  apiBase,
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
} from "./detection_workspace_utils";
import { useWorkspaceShell } from "./workspace_shell_context";

export function ProjectConnectionPage() {
  const searchParams = useSearchParams();
  const { setShellError } = useWorkspaceShell();

  const [sshSettings, setSSHSettings] = useState<SSHSettings>(defaultSSHSettings());
  const [sshStatus, setSSHStatus] = useState<SSHStatus | null>(null);
  const [sshDiagnostics, setSSHDiagnostics] = useState<SSHDiagnosticStep[]>([]);
  const [sshBusyAction, setSSHBusyAction] = useState("");
  const [sshMessage, setSSHMessage] = useState("");
  const [isEditingConnection, setIsEditingConnection] = useState(false);
  const [editRequestConsumed, setEditRequestConsumed] = useState(false);
  const [preflightResult, setPreflightResult] = useState<PreflightResult | null>(null);
  const [preflightBusy, setPreflightBusy] = useState(false);
  const [preflightLoaded, setPreflightLoaded] = useState(false);
  const [preflightError, setPreflightError] = useState("");
  const [remoteEnvStatus, setRemoteEnvStatus] = useState<RemoteEnvStatus | null>(null);
  const [remoteEnvBusy, setRemoteEnvBusy] = useState(false);
  const [remoteEnvLoaded, setRemoteEnvLoaded] = useState(false);
  const [remoteEnvError, setRemoteEnvError] = useState("");
  const [envInstallJobId, setEnvInstallJobId] = useState("");
  const [envInstallTarget, setEnvInstallTarget] = useState<"" | "miniforge" | "workflow_runtime">("");
  const [envInstallSnapshot, setEnvInstallSnapshot] = useState<InstallJobSnapshot | null>(null);
  const [envInstallBusy, setEnvInstallBusy] = useState(false);
  const [expandedEnvLogs, setExpandedEnvLogs] = useState<string[]>([]);
  const [preflightExpanded, setPreflightExpanded] = useState(false);
  const [preflightExpandedTouched, setPreflightExpandedTouched] = useState(false);

  const isConnected = sshStatus?.connected === true;
  const canEditForm = !isConnected || isEditingConnection;
  const buttonsLocked = sshBusyAction.length > 0 || (isConnected && !isEditingConnection);

  const loadPreflight = async () => {
    setPreflightBusy(true);
    setPreflightError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/ssh/preflight`, { method: "POST" });
      const data = await readJsonOrThrow(resp);
      const nextResult = parsePreflightResult(data?.item);
      if (!nextResult) {
        throw new Error("服务器预检返回格式无效。");
      }
      setPreflightResult(nextResult);
      setPreflightLoaded(true);
      if (!preflightExpandedTouched) {
        setPreflightExpanded(!nextResult.ok || nextResult.warnings.length > 0);
      }
    } catch (err) {
      setPreflightResult(null);
      setPreflightLoaded(true);
      setPreflightError(err instanceof Error ? err.message : String(err));
      if (!preflightExpandedTouched) {
        setPreflightExpanded(true);
      }
    } finally {
      setPreflightBusy(false);
    }
  };

  const loadRemoteEnvStatus = async (options?: { silent?: boolean }) => {
    if (!options?.silent) {
      setRemoteEnvBusy(true);
    }
    setRemoteEnvError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/ssh/env/status`);
      const data = await readJsonOrThrow(resp);
      const nextStatus = parseRemoteEnvStatus(data?.item);
      if (!nextStatus) {
        throw new Error("运行环境返回格式无效。");
      }
      setRemoteEnvStatus(nextStatus);
      setRemoteEnvLoaded(true);
      if (envInstallTarget !== "workflow_runtime") {
        if (nextStatus.miniforge.status === "running" || nextStatus.miniforge.status === "installing") {
          setEnvInstallTarget("miniforge");
          setEnvInstallJobId(nextStatus.miniforge.job_id);
        } else {
          setEnvInstallJobId("");
          setEnvInstallTarget("");
          setEnvInstallSnapshot(null);
        }
      }
    } catch (err) {
      setRemoteEnvStatus(null);
      setRemoteEnvLoaded(true);
      setRemoteEnvError(err instanceof Error ? err.message : String(err));
    } finally {
      if (!options?.silent) {
        setRemoteEnvBusy(false);
      }
    }
  };

  const toggleEnvLog = (key: string) => {
    setExpandedEnvLogs((prev) => (prev.includes(key) ? prev.filter((item) => item !== key) : [...prev, key]));
  };

  const startMiniforgeInstall = async () => {
    setRemoteEnvError("");
    setEnvInstallBusy(true);
    setEnvInstallTarget("miniforge");
    setEnvInstallSnapshot(null);
    try {
      const resp = await fetch(`${apiBase()}/api/v1/ssh/env/install`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: "miniforge" }),
      });
      const data = await readJsonOrThrow(resp);
      const nextJobId = safeText(data?.item?.job_id);
      if (!nextJobId) {
        throw new Error("Conda Runtime 安装任务返回缺少 job_id。");
      }
      setEnvInstallJobId(nextJobId);
      setExpandedEnvLogs((prev) => (prev.includes("miniforge") ? prev : [...prev, "miniforge"]));
      await loadRemoteEnvStatus({ silent: true });
    } catch (err) {
      setRemoteEnvError(err instanceof Error ? err.message : String(err));
      setEnvInstallTarget("");
    } finally {
      setEnvInstallBusy(false);
    }
  };

  const startWorkflowRuntimeInstall = async () => {
    const profileKind = preflightResult?.recommended_profile_details?.profile_kind;
    if (!profileKind) {
      setRemoteEnvError("当前预检结果缺少推荐 profile，无法启动 workflow runtime 安装。");
      return;
    }
    setRemoteEnvError("");
    setEnvInstallBusy(true);
    setEnvInstallTarget("workflow_runtime");
    setEnvInstallSnapshot(null);
    try {
      const resp = await fetch(`${apiBase()}/api/v1/ssh/env/install`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: "workflow_runtime", profile_kind: profileKind }),
      });
      const data = await readJsonOrThrow(resp);
      const nextJobId = safeText(data?.item?.job_id);
      if (!nextJobId) {
        throw new Error("Workflow runtime 安装任务返回缺少 job_id。");
      }
      setEnvInstallJobId(nextJobId);
      setExpandedEnvLogs((prev) => (prev.includes("workflow_runtime") ? prev : [...prev, "workflow_runtime"]));
    } catch (err) {
      setRemoteEnvError(err instanceof Error ? err.message : String(err));
      setEnvInstallTarget("");
    } finally {
      setEnvInstallBusy(false);
    }
  };

  const loadEnvInstallSnapshot = async (jobId: string) => {
    const resp = await fetch(`${apiBase()}/api/v1/ssh/env/install/${encodeURIComponent(jobId)}`);
    const data = await readJsonOrThrow(resp);
    const nextSnapshot = parseInstallJobSnapshot(data?.item);
    if (!nextSnapshot) {
      throw new Error("运行环境安装任务返回格式无效。");
    }
    setEnvInstallSnapshot(nextSnapshot);
    if (nextSnapshot.done) {
      setEnvInstallJobId("");
      setEnvInstallTarget("");
      await loadRemoteEnvStatus({ silent: true });
    }
  };

  const syncFromServer = async () => {
    const [settingsResp, statusResp] = await Promise.all([
      fetch(`${apiBase()}/api/v1/settings`),
      fetch(`${apiBase()}/api/v1/ssh/status`),
    ]);
    const settingsData = await readJsonOrThrow(settingsResp);
    const statusData = await readJsonOrThrow(statusResp);
    const payload = parseSettingsPayload(settingsData?.item);
    setSSHSettings(parseSSHSettings(payload.ssh));
    const nextStatus = parseSSHStatus(statusData?.item);
    setSSHStatus(nextStatus);
    if (nextStatus?.connected) {
      setIsEditingConnection(false);
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

  const updateSSHField = <K extends keyof SSHSettings,>(key: K, value: SSHSettings[K]) => {
    setSSHSettings((prev) => ({ ...prev, [key]: value }));
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
      await loadPreflight();
      await loadRemoteEnvStatus();
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
      setSSHMessage("");
      setPreflightResult(null);
      setPreflightLoaded(false);
      setPreflightError("");
      setRemoteEnvStatus(null);
      setRemoteEnvLoaded(false);
      setRemoteEnvError("");
      setEnvInstallJobId("");
      setEnvInstallTarget("");
      setEnvInstallSnapshot(null);
      setExpandedEnvLogs([]);
      setPreflightExpanded(false);
      setPreflightExpandedTouched(false);
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

  useEffect(() => {
    if (searchParams.get("edit") !== "1" || editRequestConsumed || !sshStatus?.connected || isEditingConnection || sshBusyAction) {
      return;
    }
    setEditRequestConsumed(true);
    void startConnectionEdit();
  }, [editRequestConsumed, isEditingConnection, searchParams, sshBusyAction, sshStatus?.connected]);

  useEffect(() => {
    if (!isConnected || preflightLoaded || preflightBusy) {
      return;
    }
    void loadPreflight();
  }, [isConnected, preflightBusy, preflightLoaded]);

  useEffect(() => {
    if (!isConnected || remoteEnvLoaded || remoteEnvBusy) {
      return;
    }
    void loadRemoteEnvStatus({ silent: true });
  }, [isConnected, remoteEnvBusy, remoteEnvLoaded]);

  useEffect(() => {
    if (!envInstallJobId) {
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      if (cancelled) {
        return;
      }
      void loadEnvInstallSnapshot(envInstallJobId).catch((err) => {
        if (!cancelled) {
          setRemoteEnvError(err instanceof Error ? err.message : String(err));
        }
      });
    }, 3000);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [envInstallJobId]);

  const condaRuntimeInstalling =
    (envInstallBusy && envInstallTarget === "miniforge") ||
    (envInstallJobId.length > 0 && envInstallTarget === "miniforge") ||
    remoteEnvStatus?.miniforge.status === "running" ||
    remoteEnvStatus?.miniforge.status === "installing";
  const workflowRuntimeInstalling =
    (envInstallBusy && envInstallTarget === "workflow_runtime") ||
    (envInstallJobId.length > 0 && envInstallTarget === "workflow_runtime") ||
    envInstallJobId.startsWith("h2o_workflow_bootstrap_");
  const recommendedWorkflowProfile = preflightResult?.recommended_profile_details?.profile_kind || preflightResult?.recommended_profile || "";

  const shouldShowPreflightValue = (check: PreflightResult["checks"][number]) =>
    check.key === "arch" || check.key === "disk" || check.status !== "ok";
  const preflightProblemChecks = preflightResult ? preflightResult.checks.filter((check) => check.status !== "ok") : [];
  const preflightHasIssues = !!preflightResult && (preflightProblemChecks.length > 0 || preflightResult.failures.length > 0 || preflightResult.warnings.length > 0 || !preflightResult.ok);
  const preflightPanelVisible = isConnected && (!!preflightError || preflightHasIssues || (preflightBusy && !preflightLoaded));
  const condaRuntimeIssue = remoteEnvStatus
    ? {
        key: "conda_runtime",
        name: "Conda Runtime",
        message: condaRuntimeInstalling
          ? "Conda Runtime 安装中，完成后即可作为 workflow conda fallback 使用。"
          : "未检测到 Conda Runtime。若服务器缺少容器运行时或 workflow 缺少容器元数据，请先安装它。",
        logText: envInstallSnapshot?.log_text || remoteEnvStatus.miniforge.log_text || "",
        installAction: !condaRuntimeInstalling,
      }
    : null;
  const remoteEnvHasIssues = !!condaRuntimeIssue || !!remoteEnvError;

  return (
    <section className="settings-layout settings-layout--single">
      <section className="settings-column">
        <section className="settings-editor-panel connection-panel">
          <div className="connection-status-row">
            <span className={`status-pill${sshStatus?.connected ? " status-pill--ok" : ""}`}>{sshStatus?.connected ? "已连接" : "未连接"}</span>
            {sshMessage ? <span className="muted">{sshMessage}</span> : null}
          </div>

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

          {isConnected && (preflightBusy || !!preflightError || preflightHasIssues) ? (
            <div className="connection-inline-note">
              <span className="muted">
                {preflightBusy && !preflightLoaded
                  ? "正在检测服务器环境"
                  : preflightError
                    ? "服务器状态检查失败"
                    : preflightHasIssues
                      ? `服务器存在 ${preflightProblemChecks.length || 1} 个待处理问题`
                      : ""}
              </span>
            </div>
          ) : null}

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

        {preflightPanelVisible ? (
          <section className="settings-editor-panel connection-panel preflight-panel">
            <div className="connection-section-head">
              <div className="connection-section-title-wrap">
                <h2 className="settings-section-title">状态检查</h2>
              </div>
              <div className="settings-actions connection-section-actions">
                <span className="connection-inline-status muted">
                  {preflightBusy && !preflightLoaded
                    ? "正在检测服务器环境"
                    : preflightError
                      ? "预检失败"
                      : preflightResult?.ok
                        ? "服务器已就绪"
                        : "预检发现问题"}
                </span>
                <button className="ui-button" type="button" disabled={preflightBusy} onClick={() => void loadPreflight()}>
                  {preflightBusy ? "检测中..." : "重新检测"}
                </button>
                <button
                  className="ui-button"
                  type="button"
                  disabled={preflightBusy || !recommendedWorkflowProfile || workflowRuntimeInstalling}
                  onClick={() => void startWorkflowRuntimeInstall()}
                >
                  {workflowRuntimeInstalling ? "安装中..." : "安装 Workflow Runtime"}
                </button>
                {preflightHasIssues ? (
                  <button
                    className="control-btn connection-section-toggle"
                    type="button"
                    aria-expanded={preflightExpanded}
                    onClick={() => {
                      setPreflightExpandedTouched(true);
                      setPreflightExpanded((prev) => !prev);
                    }}
                  >
                    <ChevronRightIcon className={`connection-section-toggle-icon${preflightExpanded ? " expanded" : ""}`} />
                    <span>{preflightExpanded ? "收起问题" : "查看问题"}</span>
                  </button>
                ) : null}
              </div>
            </div>

            {preflightError ? <p className="fail-text">{preflightError}</p> : null}

            {preflightResult ? (
              <>
                {recommendedWorkflowProfile ? (
                  <p className="muted">推荐 profile: {recommendedWorkflowProfile}</p>
                ) : null}

                {preflightResult.failures.length > 0 ? (
                  <div className="preflight-message-list">
                    {preflightResult.failures.map((item) => (
                      <p key={item} className="fail-text">
                        {item}
                      </p>
                    ))}
                  </div>
                ) : null}

                {preflightResult.warnings.length > 0 ? (
                  <div className="preflight-message-list">
                    {preflightResult.warnings.map((item) => (
                      <p key={item} className="muted">
                        {item}
                      </p>
                    ))}
                  </div>
                ) : null}

                {preflightExpanded && preflightHasIssues ? (
                  <div className="connection-detail-list">
                    {preflightProblemChecks.map((check) => (
                      <article key={check.key} className={`connection-detail-item connection-detail-item--${check.status}`}>
                        <div className="connection-detail-item-top">
                          <strong>{check.label}</strong>
                          <div className="connection-detail-item-side">
                            {check.status !== "ok" ? <span className="status-pill">{check.status}</span> : null}
                            {shouldShowPreflightValue(check) ? <span className="connection-detail-value">{check.value || "unknown"}</span> : null}
                          </div>
                        </div>
                        {check.status !== "ok" ? <p className="muted">{check.message || "无额外信息"}</p> : null}
                      </article>
                    ))}
                  </div>
                ) : null}

                {workflowRuntimeInstalling || envInstallTarget === "workflow_runtime" ? (
                  <article className="connection-detail-item connection-detail-item--warn">
                    <div className="connection-detail-item-top">
                      <strong>Workflow Runtime Bootstrap</strong>
                      <div className="connection-detail-item-side">
                        <span className="status-pill">{envInstallSnapshot?.status || "running"}</span>
                      </div>
                    </div>
                    <p className="muted">
                      正在为 {safeText(envInstallSnapshot?.progress?.profile_kind, recommendedWorkflowProfile) || "当前推荐 profile"} 安装 workflow runtime。
                    </p>
                    {envInstallSnapshot?.log_text ? <pre className="connection-log-preview">{envInstallSnapshot.log_text}</pre> : null}
                  </article>
                ) : null}
              </>
            ) : null}

            {preflightBusy && !preflightResult ? <p className="muted">正在获取预检结果...</p> : null}
          </section>
        ) : null}

        {isConnected ? (
          <section className="settings-editor-panel connection-panel remote-env-panel">
            <div className="connection-section-head">
              <div className="connection-section-title-wrap">
                <h2 className="settings-section-title">Runtime Bootstrap</h2>
              </div>
              <div className="settings-actions connection-section-actions">
                <span className="connection-inline-status muted">
                  {remoteEnvBusy && !remoteEnvLoaded
                    ? "正在读取 Runtime Bootstrap 状态"
                    : remoteEnvError
                      ? "环境状态读取失败"
                      : remoteEnvHasIssues
                        ? (condaRuntimeInstalling ? "正在安装 Conda Runtime" : "Conda Runtime 待安装")
                        : "Workflow Runtime Bootstrap 已就绪"}
                </span>
                <button className="ui-button" type="button" disabled={remoteEnvBusy || condaRuntimeInstalling} onClick={() => void loadRemoteEnvStatus()}>
                  {remoteEnvBusy ? "刷新中..." : "刷新状态"}
                </button>
              </div>
            </div>

            {remoteEnvError ? <p className="fail-text">{remoteEnvError}</p> : null}

            {remoteEnvStatus ? (
              <>
                {condaRuntimeIssue ? (
                  <div className="env-status-list">
                    <article className="env-status-card env-status-card--primary">
                      <div className="env-status-row">
                        <div className="env-status-main">
                          <strong>{condaRuntimeIssue.name}</strong>
                          <p className="muted">{condaRuntimeIssue.message}</p>
                        </div>
                        <div className="env-status-side">
                          {condaRuntimeIssue.installAction ? (
                            <button className="ui-button ui-button--primary" type="button" disabled={condaRuntimeInstalling} onClick={() => void startMiniforgeInstall()}>
                              {condaRuntimeInstalling ? "安装中..." : "安装 Conda Runtime"}
                            </button>
                          ) : null}
                          {condaRuntimeIssue.logText ? (
                            <button className="ui-button" type="button" onClick={() => toggleEnvLog(condaRuntimeIssue.key)}>
                              {expandedEnvLogs.includes(condaRuntimeIssue.key) ? "收起日志" : "查看日志"}
                            </button>
                          ) : null}
                        </div>
                      </div>

                      {expandedEnvLogs.includes(condaRuntimeIssue.key) ? <pre className="env-log-block">{condaRuntimeIssue.logText}</pre> : null}
                    </article>
                  </div>
                ) : (
                  <div className="env-status-list">
                    <article className="env-status-card">
                      <div className="env-status-row">
                        <div className="env-status-main">
                          <strong>Conda Runtime</strong>
                          <p className="muted">
                            已检测到基础 conda 运行时，可为缺少容器元数据或容器运行时的 workflow 提供 fallback。
                          </p>
                        </div>
                        <div className="env-status-side">
                          <span className="status-pill">ready</span>
                          <span className="badge">{safeText(remoteEnvStatus.miniforge.conda_executable, remoteEnvStatus.miniforge.version || "available")}</span>
                        </div>
                      </div>
                    </article>
                  </div>
                )}
              </>
            ) : null}

            {remoteEnvBusy && !remoteEnvStatus ? <p className="muted">正在获取运行环境状态...</p> : null}
          </section>
        ) : null}
      </section>
    </section>
  );
}
