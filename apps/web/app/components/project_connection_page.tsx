"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { open } from "@tauri-apps/plugin-dialog";

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

  const isConnected = sshStatus?.connected === true;
  const canEditForm = !isConnected || isEditingConnection;
  const buttonsLocked = sshBusyAction.length > 0 || (isConnected && !isEditingConnection);

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

  return (
    <section className="settings-layout">
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
      </section>
    </section>
  );
}
