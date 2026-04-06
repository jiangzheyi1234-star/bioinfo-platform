"use client";

import { useEffect, useState } from "react";

import { ProjectWorkspaceShell } from "./project_workspace_shell";
import type { SSHDiagnosticStep, SSHSettings, SSHStatus } from "./detection_workspace_types";
import {
  apiBase,
  defaultSSHSettings,
  parseSettingsPayload,
  parseSSHDiagnosticSteps,
  parseSSHSettings,
  parseSSHStatus,
  readJsonOrThrow,
  safeText,
} from "./detection_workspace_utils";
import { WorkspaceSectionHeader } from "./workspace_section_primitives";
import { useProjectWorkspaceSidebarState } from "./use_project_workspace_sidebar_state";

export function ProjectConnectionPage() {
  const {
    projects,
    currentProjectId,
    tasks,
    selectedTaskId,
    error: sidebarError,
    setError: setSidebarError,
    selectProject,
    selectTask,
  } = useProjectWorkspaceSidebarState();

  const [sshSettings, setSSHSettings] = useState<SSHSettings>(defaultSSHSettings());
  const [sshStatus, setSSHStatus] = useState<SSHStatus | null>(null);
  const [sshDiagnostics, setSSHDiagnostics] = useState<SSHDiagnosticStep[]>([]);
  const [sshBusyAction, setSSHBusyAction] = useState<string>("");
  const [sshMessage, setSSHMessage] = useState<string>("");
  const [pageError, setPageError] = useState<string>("");

  const syncFromServer = async () => {
    const [settingsResp, statusResp] = await Promise.all([
      fetch(`${apiBase()}/api/v1/settings`),
      fetch(`${apiBase()}/api/v1/ssh/status`),
    ]);
    const settingsData = await readJsonOrThrow(settingsResp);
    const statusData = await readJsonOrThrow(statusResp);
    const payload = parseSettingsPayload(settingsData?.item);
    setSSHSettings(parseSSHSettings(payload.ssh));
    setSSHStatus(parseSSHStatus(statusData?.item));
  };

  useEffect(() => {
    void (async () => {
      try {
        await syncFromServer();
      } catch (err) {
        setPageError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, []);

  const updateSSHField = <K extends keyof SSHSettings>(key: K, value: SSHSettings[K]) => {
    setSSHSettings((prev) => ({ ...prev, [key]: value }));
  };

  const saveSSHSettings = async () => {
    setPageError("");
    setSidebarError("");
    setSSHMessage("");
    setSSHBusyAction("save");
    try {
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
      setSSHMessage("SSH 设置已保存");
      const statusResp = await fetch(`${apiBase()}/api/v1/ssh/status`);
      const statusData = await readJsonOrThrow(statusResp);
      setSSHStatus(parseSSHStatus(statusData?.item));
    } catch (err) {
      setPageError(err instanceof Error ? err.message : String(err));
    } finally {
      setSSHBusyAction("");
    }
  };

  const connectSSH = async () => {
    setPageError("");
    setSidebarError("");
    setSSHMessage("");
    setSSHBusyAction("connect");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/ssh/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(sshSettings),
      });
      const data = await readJsonOrThrow(resp);
      setSSHStatus(parseSSHStatus(data?.item));
      setSSHDiagnostics([]);
      setSSHMessage(safeText(data?.item?.message, "SSH 已连接"));
    } catch (err) {
      setPageError(err instanceof Error ? err.message : String(err));
    } finally {
      setSSHBusyAction("");
    }
  };

  const disconnectSSH = async () => {
    setPageError("");
    setSidebarError("");
    setSSHMessage("");
    setSSHBusyAction("disconnect");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/ssh/disconnect`, {
        method: "POST",
      });
      const data = await readJsonOrThrow(resp);
      setSSHStatus(parseSSHStatus(data?.item));
      setSSHDiagnostics([]);
      setSSHMessage(safeText(data?.item?.message, "SSH 已断开"));
    } catch (err) {
      setPageError(err instanceof Error ? err.message : String(err));
    } finally {
      setSSHBusyAction("");
    }
  };

  const testSSH = async () => {
    setPageError("");
    setSidebarError("");
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
      setPageError(err instanceof Error ? err.message : String(err));
    } finally {
      setSSHBusyAction("");
    }
  };

  return (
    <ProjectWorkspaceShell
      activeView="connect"
      projects={projects}
      currentProjectId={currentProjectId}
      tasks={tasks}
      selectedTaskId={selectedTaskId}
      error={pageError || sidebarError}
      onSelectProject={selectProject}
      onSelectTask={selectTask}
    >
      <section className="settings-layout">
        <section className="settings-column">
          <section className="settings-editor-panel connection-panel">
            <WorkspaceSectionHeader title="连接" description="SSH" />

            <div className="connection-status-row">
              <span className={`status-pill${sshStatus?.connected ? " status-pill--ok" : ""}`}>{sshStatus?.connected ? "已连接" : "未连接"}</span>
              <span className="muted text-sm">{sshStatus?.message || "填写参数后连接远端主机"}</span>
            </div>

            <div className="settings-form-grid">
              <div className="field-block">
                <label className="field-label" htmlFor="ssh-host">
                  Host
                </label>
                <input id="ssh-host" className="control-input" value={sshSettings.host} onChange={(event) => updateSSHField("host", event.target.value)} placeholder="192.168.0.152" />
              </div>
              <div className="field-block">
                <label className="field-label" htmlFor="ssh-port">
                  Port
                </label>
                <input id="ssh-port" className="control-input" type="number" value={sshSettings.port} onChange={(event) => updateSSHField("port", Number(event.target.value || 22))} placeholder="22" />
              </div>
              <div className="field-block">
                <label className="field-label" htmlFor="ssh-user">
                  User
                </label>
                <input id="ssh-user" className="control-input" value={sshSettings.user} onChange={(event) => updateSSHField("user", event.target.value)} placeholder="ubuntu" />
              </div>
              <div className="field-block">
                <label className="field-label" htmlFor="ssh-password">
                  Password
                </label>
                <input id="ssh-password" className="control-input" type="password" value={sshSettings.password} onChange={(event) => updateSSHField("password", event.target.value)} placeholder={sshSettings.use_key ? "密钥模式下可留空" : "输入 SSH 密码"} />
              </div>
              <div className="field-block field-block--full">
                <label className="field-label" htmlFor="ssh-key-file">
                  Key File
                </label>
                <input id="ssh-key-file" className="control-input" value={sshSettings.key_file} onChange={(event) => updateSSHField("key_file", event.target.value)} placeholder="~/.ssh/id_rsa" />
              </div>
              <label className="checkbox-row field-block--full" htmlFor="ssh-use-key">
                <input id="ssh-use-key" type="checkbox" checked={sshSettings.use_key} onChange={(event) => updateSSHField("use_key", event.target.checked)} />
                <span>使用密钥连接</span>
              </label>
            </div>

            <div className="settings-actions connection-actions">
              <button className="control-btn" onClick={() => void syncFromServer()}>
                刷新
              </button>
              <button className="ui-button" disabled={sshBusyAction === "test"} onClick={() => void testSSH()}>
                {sshBusyAction === "test" ? "测试中..." : "测试"}
              </button>
              <button className="ui-button ui-button--primary" disabled={sshBusyAction === "connect"} onClick={() => void connectSSH()}>
                {sshBusyAction === "connect" ? "连接中..." : "连接"}
              </button>
              <button className="control-btn" disabled={sshBusyAction === "disconnect"} onClick={() => void disconnectSSH()}>
                {sshBusyAction === "disconnect" ? "断开中..." : "断开"}
              </button>
              <button className="control-btn" disabled={sshBusyAction === "save"} onClick={() => void saveSSHSettings()}>
                {sshBusyAction === "save" ? "保存中..." : "保存"}
              </button>
            </div>

            {sshMessage ? <p className="ok-text">{sshMessage}</p> : null}

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
        </section>
      </section>
    </ProjectWorkspaceShell>
  );
}
