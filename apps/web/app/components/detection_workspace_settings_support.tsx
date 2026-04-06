"use client";

import type { SettingsPayload, SSHSettings, SSHStatus } from "./detection_workspace_types";
import { prettyJson } from "./detection_workspace_utils";
import { WorkspaceSectionHeader } from "./workspace_section_primitives";

type SettingsPreviewPanelProps = {
  parsedSettings: SettingsPayload | null;
  sshSettings: SSHSettings;
  sshStatus: SSHStatus | null;
};

export function SettingsPreviewPanel({ parsedSettings, sshSettings, sshStatus }: SettingsPreviewPanelProps) {
  return (
    <section className="settings-preview-panel">
      <WorkspaceSectionHeader
        title="当前连接摘要"
        description="连接状态和配置快照保持可见，避免在 JSON 中迷路"
      />
      <div className="kv-list">
        <div className="kv-row">
          <span className="kv-key">状态</span>
          <span className="kv-value">{sshStatus?.message || "未加载"}</span>
        </div>
        <div className="kv-row">
          <span className="kv-key">Host</span>
          <span className="kv-value">{sshStatus?.host || sshSettings.host || "-"}</span>
        </div>
        <div className="kv-row">
          <span className="kv-key">User</span>
          <span className="kv-value">{sshStatus?.user || sshSettings.user || "-"}</span>
        </div>
        <div className="kv-row">
          <span className="kv-key">认证方式</span>
          <span className="kv-value">{sshSettings.use_key ? "密钥" : "密码"}</span>
        </div>
        <div className="kv-row">
          <span className="kv-key">Key File</span>
          <span className="kv-value">{sshSettings.key_file || "-"}</span>
        </div>
      </div>

      <WorkspaceSectionHeader title="结构预览" description="用于快速确认关键字段是否存在" className="settings-preview-divider" />
      <pre className="json-preview">{prettyJson(parsedSettings || {})}</pre>
    </section>
  );
}
