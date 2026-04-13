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
  const [envInstallSnapshot, setEnvInstallSnapshot] = useState<InstallJobSnapshot | null>(null);
  const [envInstallBusy, setEnvInstallBusy] = useState(false);
  const [expandedEnvLogs, setExpandedEnvLogs] = useState<string[]>([]);
  const [preflightExpanded, setPreflightExpanded] = useState(false);
  const [preflightExpandedTouched, setPreflightExpandedTouched] = useState(false);
  const [remoteEnvExpanded, setRemoteEnvExpanded] = useState(false);
  const [remoteEnvExpandedTouched, setRemoteEnvExpandedTouched] = useState(false);

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
      if (nextStatus.miniforge.status === "running" || nextStatus.miniforge.status === "installing") {
        setEnvInstallJobId(nextStatus.miniforge.job_id);
      } else {
        setEnvInstallJobId("");
        setEnvInstallSnapshot(null);
      }
      if (!remoteEnvExpandedTouched) {
        const shouldExpand =
          !nextStatus.miniforge.installed ||
          nextStatus.tool_envs.some((item) => item.status !== "installed");
        setRemoteEnvExpanded(shouldExpand);
      }
    } catch (err) {
      setRemoteEnvStatus(null);
      setRemoteEnvLoaded(true);
      setRemoteEnvError(err instanceof Error ? err.message : String(err));
      if (!remoteEnvExpandedTouched) {
        setRemoteEnvExpanded(true);
      }
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
        throw new Error("Miniforge 安装任务返回缺少 job_id。");
      }
      setEnvInstallJobId(nextJobId);
      setExpandedEnvLogs((prev) => (prev.includes("miniforge") ? prev : [...prev, "miniforge"]));
      await loadRemoteEnvStatus({ silent: true });
    } catch (err) {
      setRemoteEnvError(err instanceof Error ? err.message : String(err));
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

  const updateSSHField = <K extends keyof SSHSettings>(key: K, value: SSHSettings[K]) => {
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
      setEnvInstallSnapshot(null);
      setExpandedEnvLogs([]);
      setPreflightExpanded(false);
      setPreflightExpandedTouched(false);
      setRemoteEnvExpanded(false);
      setRemoteEnvExpandedTouched(false);
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

  const miniforgeInstalling =
    envInstallBusy ||
    envInstallJobId.length > 0 ||
    remoteEnvStatus?.miniforge.status === "running" ||
    remoteEnvStatus?.miniforge.status === "installing";

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
          <section className="settings-editor-panel connection-panel preflight-panel">
            <div className="connection-section-head">
              <div className="connection-section-title-wrap">
                <h2 className="settings-section-title">服务器预检</h2>
                <p className="muted preflight-summary">
                  {preflightBusy && !preflightLoaded
                    ? "正在检测当前服务器是否满足后续安装与运行条件。"
                    : preflightError
                      ? "预检失败，请先修复连接或服务器环境问题。"
                      : preflightResult?.ok
                        ? "预检通过，可以继续配置运行环境。"
                        : "预检发现问题，建议先处理失败项。"}
                </p>
              </div>
              <div className="settings-actions connection-section-actions">
                <button className="ui-button" type="button" disabled={preflightBusy} onClick={() => void loadPreflight()}>
                  {preflightBusy ? "检测中..." : "重新检测"}
                </button>
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
                  <span>{preflightExpanded ? "收起详情" : "查看详情"}</span>
                </button>
              </div>
            </div>

            {preflightError ? <p className="fail-text">{preflightError}</p> : null}

            {preflightResult ? (
              <>
                <div className="connection-meta-row connection-summary-row">
                  <span className={`status-pill${preflightResult.ok ? " status-pill--ok" : ""}`}>{preflightResult.ok ? "预检通过" : "预检异常"}</span>
                </div>

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

                {preflightExpanded ? (
                  <div className="connection-detail-list">
                    {preflightResult.checks.map((check) => (
                      <article key={check.key} className={`connection-detail-card connection-detail-card--${check.status}`}>
                        <div className="connection-detail-card-head">
                          <strong>{check.label}</strong>
                          {check.status !== "ok" ? <span className="status-pill">{check.status}</span> : null}
                        </div>
                        <div className="connection-detail-card-body">
                          <span className="connection-detail-value">{check.value || "unknown"}</span>
                          <p className="muted">{check.message || "无额外信息"}</p>
                        </div>
                      </article>
                    ))}
                  </div>
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
                <h2 className="settings-section-title">运行环境</h2>
                <p className="muted preflight-summary">
                  {remoteEnvBusy && !remoteEnvLoaded
                    ? "正在读取远端 conda 与工具环境状态。"
                    : remoteEnvError
                      ? "环境状态读取失败，请检查 SSH 连接或服务端日志。"
                      : "这里显示 Miniforge 与工具环境的当前可用性。"}
                </p>
              </div>
              <div className="settings-actions connection-section-actions">
                <button className="ui-button" type="button" disabled={remoteEnvBusy || miniforgeInstalling} onClick={() => void loadRemoteEnvStatus()}>
                  {remoteEnvBusy ? "刷新中..." : "刷新状态"}
                </button>
                <button
                  className="control-btn connection-section-toggle"
                  type="button"
                  aria-expanded={remoteEnvExpanded}
                  onClick={() => {
                    setRemoteEnvExpandedTouched(true);
                    setRemoteEnvExpanded((prev) => !prev);
                  }}
                >
                  <ChevronRightIcon className={`connection-section-toggle-icon${remoteEnvExpanded ? " expanded" : ""}`} />
                  <span>{remoteEnvExpanded ? "收起详情" : "查看详情"}</span>
                </button>
              </div>
            </div>

            {remoteEnvError ? <p className="fail-text">{remoteEnvError}</p> : null}

            {remoteEnvStatus ? (
              <>
                <div className="connection-meta-row connection-summary-row">
                  <span className={`status-pill${remoteEnvStatus.miniforge.installed ? " status-pill--ok" : ""}`}>
                    {remoteEnvStatus.miniforge.installed ? "Miniforge 已就绪" : "Miniforge 未就绪"}
                  </span>
                  <span className="badge">已安装环境 {remoteEnvStatus.summary.installed}/{remoteEnvStatus.summary.total}</span>
                  {miniforgeInstalling ? <span className="badge">安装中</span> : null}
                </div>

                {remoteEnvExpanded ? (
                  <div className="env-status-list">
                    <article className="env-status-card">
                      <div className="env-status-row">
                        <div className="env-status-main">
                          <strong>Miniforge</strong>
                          <p className="muted">{remoteEnvStatus.miniforge.message || "无额外信息"}</p>
                        </div>
                        <div className="env-status-side">
                          {!remoteEnvStatus.miniforge.installed ? <span className="status-pill">{remoteEnvStatus.miniforge.status || "unknown"}</span> : null}
                          <span className="badge">{remoteEnvStatus.miniforge.version || remoteEnvStatus.miniforge.status || "unknown"}</span>
                          {!remoteEnvStatus.miniforge.installed ? (
                            <button className="ui-button ui-button--primary" type="button" disabled={miniforgeInstalling} onClick={() => void startMiniforgeInstall()}>
                              {miniforgeInstalling ? "安装中..." : "安装"}
                            </button>
                          ) : null}
                          {(remoteEnvStatus.miniforge.log_text || envInstallSnapshot?.log_text) ? (
                            <button className="ui-button" type="button" onClick={() => toggleEnvLog("miniforge")}>
                              {expandedEnvLogs.includes("miniforge") ? "收起日志" : "查看日志"}
                            </button>
                          ) : null}
                        </div>
                      </div>

                      {expandedEnvLogs.includes("miniforge") ? (
                        <pre className="env-log-block">{envInstallSnapshot?.log_text || remoteEnvStatus.miniforge.log_text || "暂无日志"}</pre>
                      ) : null}
                    </article>

                    {remoteEnvStatus.tool_envs.map((toolEnv) => (
                      <article key={toolEnv.tool_id} className="env-status-card">
                        <div className="env-status-row">
                          <div className="env-status-main">
                            <strong>{toolEnv.name}</strong>
                            <p className="muted">{toolEnv.message || toolEnv.env_name || "无额外信息"}</p>
                          </div>
                          <div className="env-status-side">
                            {!toolEnv.installed ? <span className="status-pill">{toolEnv.status}</span> : null}
                            <span className="badge">{toolEnv.version || toolEnv.env_name || toolEnv.tool_id}</span>
                            {toolEnv.log_text ? (
                              <button className="ui-button" type="button" onClick={() => toggleEnvLog(toolEnv.tool_id)}>
                                {expandedEnvLogs.includes(toolEnv.tool_id) ? "收起日志" : "查看日志"}
                              </button>
                            ) : null}
                          </div>
                        </div>

                        {expandedEnvLogs.includes(toolEnv.tool_id) ? <pre className="env-log-block">{toolEnv.log_text}</pre> : null}
                      </article>
                    ))}
                  </div>
                ) : null}
              </>
            ) : null}

            {remoteEnvBusy && !remoteEnvStatus ? <p className="muted">正在获取运行环境状态...</p> : null}
          </section>
        ) : null}
      </section>
    </section>
  );
}
