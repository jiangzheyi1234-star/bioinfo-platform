"use client";

import { SettingsPreviewPanel } from "./detection_workspace_settings_support";
import { ToolRunForm } from "./tool_run_form";
import type {
  DatabaseEntry,
  Execution,
  Project,
  SettingsPayload,
  SSHDiagnosticStep,
  SSHSettings,
  SSHStatus,
  ToolDescriptor,
  ToolSummary,
} from "./detection_workspace_types";
import { safeText } from "./detection_workspace_utils";
import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";

type ProjectsSectionProps = {
  projects: Project[];
  currentProjectId: string;
  onOpenProject: (projectId: string) => Promise<void>;
  onRefreshProjects: () => Promise<void>;
  createProjectName: string;
  createProjectDescription: string;
  createProjectBusy: boolean;
  createProjectMessage: string;
  onChangeCreateProjectName: (value: string) => void;
  onChangeCreateProjectDescription: (value: string) => void;
  onCreateProject: () => Promise<void>;
};

export function ProjectsSection(props: ProjectsSectionProps) {
  return (
    <div className="projects-layout">
      <section className="projects-list-panel">
        <WorkspaceSectionHeader
          title="项目列表"
          description="切换当前项目并同步桌面工作上下文"
          aside={
            <button className="control-btn" onClick={() => void props.onRefreshProjects()}>
              刷新
            </button>
          }
        />

        <div className="projects-list-grid">
          {props.projects.length === 0 ? (
            <WorkspaceEmptyState
              mark="Proj"
              label="暂无项目"
              hint="先创建项目，或从现有项目列表中切换当前工作上下文。"
              compact
            />
          ) : null}
          {props.projects.map((project) => {
            const active = project.project_id === props.currentProjectId;
            return (
              <article key={project.project_id} className={`project-list-card${active ? " active" : ""}`}>
                <div className="row">
                  <strong>{project.name}</strong>
                  <span className="badge">{project.status || "unknown"}</span>
                </div>
                <code>{project.project_id}</code>
                <p className="muted">{project.description || "无描述"}</p>
                <button
                  className="control-btn"
                  disabled={active}
                  onClick={() => {
                    void props.onOpenProject(project.project_id);
                  }}
                >
                  {active ? "当前项目" : "切换到此项目"}
                </button>
              </article>
            );
          })}
        </div>
      </section>

      <section className="projects-create-panel">
        <WorkspaceSectionHeader title="新建项目" description="创建后自动设为当前项目" />
        <div className="form-section">
          <label className="field-label" htmlFor="create-project-name">
            项目名称
          </label>
          <input
            id="create-project-name"
            className="control-input"
            value={props.createProjectName}
            onChange={(event) => props.onChangeCreateProjectName(event.target.value)}
            placeholder="例如：宏基因组批次 2026-04"
          />
        </div>
        <div className="form-section">
          <label className="field-label" htmlFor="create-project-description">
            项目描述
          </label>
          <textarea
            id="create-project-description"
            className="input-control textarea-control"
            value={props.createProjectDescription}
            onChange={(event) => props.onChangeCreateProjectDescription(event.target.value)}
            placeholder="可选：记录本次项目目标、数据来源与约束"
          />
        </div>
        <button
          className="ui-button ui-button--primary"
          disabled={props.createProjectBusy}
          onClick={() => {
            void props.onCreateProject();
          }}
        >
          {props.createProjectBusy ? "创建中..." : "创建并打开项目"}
        </button>
        {props.createProjectMessage ? <p className="ok-text">{props.createProjectMessage}</p> : null}
      </section>
    </div>
  );
}

type RunsSectionProps = {
  filteredTools: ToolSummary[];
  selectedToolId: string;
  selectedDescriptor: ToolDescriptor | null;
  toolSearch: string;
  onToolSearchChange: (value: string) => void;
  onSelectTool: (toolId: string) => Promise<void>;
  toolRunBusy: boolean;
  onRunTool: (params: Record<string, unknown>) => Promise<void>;
  toolRunMsg: string;
};

export function RunsSection({
  filteredTools,
  selectedToolId,
  selectedDescriptor,
  toolSearch,
  onToolSearchChange,
  onSelectTool,
  toolRunBusy,
  onRunTool,
  toolRunMsg,
}: RunsSectionProps) {
  return (
    <div className="tools-page-grid">
      <section className="tools-catalog-panel">
        <WorkspaceSectionHeader
          title="工具目录"
          description="按名称、类别或 ID 搜索工具"
          aside={<span className="badge">{filteredTools.length}</span>}
        />
        <input
          type="text"
          className="control-input workspace-filter-input"
          placeholder="搜索工具"
          value={toolSearch}
          onChange={(event) => onToolSearchChange(event.target.value)}
          aria-label="搜索工具"
        />
        <div className="tools-catalog-list">
          {filteredTools.length === 0 ? (
            <WorkspaceEmptyState
              mark="Run"
              label="未找到可用工具"
              hint="调整搜索关键字，或先确认工具目录已经成功加载。"
              compact
            />
          ) : null}
          {filteredTools.map((tool) => (
            <button
              key={tool.id}
              className={`tool-list-item${selectedToolId === tool.id ? " selected" : ""}`}
              onClick={() => void onSelectTool(tool.id)}
            >
              <strong>{tool.name}</strong>
              <span>{tool.description || tool.category}</span>
              <em>{tool.id}</em>
            </button>
          ))}
        </div>
      </section>

      <section className="tools-config-panel">
        {!selectedDescriptor ? (
          <WorkspaceEmptyState
            mark="Run"
            label="请选择左侧工具以配置参数并执行"
            hint="工具详情、版本和参数表单会在这里保持固定位置。"
          />
        ) : (
          <>
            <WorkspaceSectionHeader
              title={safeText(selectedDescriptor.name, selectedToolId)}
              description={safeText(selectedDescriptor.description, "当前工具未提供描述")}
              aside={
                <div className="meta-row">
                  <span className="badge">{safeText(selectedDescriptor.id, selectedToolId)}</span>
                  <span className="badge">v{safeText(selectedDescriptor.version, "unknown")}</span>
                  <span className="badge">{safeText(selectedDescriptor.category, "unknown")}</span>
                </div>
              }
            />
            <ToolRunForm descriptor={selectedDescriptor} toolId={selectedToolId} onRun={onRunTool} busy={toolRunBusy} />
            {toolRunMsg ? <p className="ok-text">{toolRunMsg}</p> : null}
          </>
        )}
      </section>
    </div>
  );
}

type HistorySectionProps = {
  historyRows: Execution[];
  historySearch: string;
  busyArchiveId: string;
  onHistorySearchChange: (value: string) => void;
  onRefresh: () => Promise<void>;
  onArchiveExecution: (executionId: string) => Promise<void>;
};

export function HistorySection({
  historyRows,
  historySearch,
  busyArchiveId,
  onHistorySearchChange,
  onRefresh,
  onArchiveExecution,
}: HistorySectionProps) {
  const query = historySearch.trim().toLowerCase();
  const visibleRows = historyRows.filter((row) => {
    if (!query) {
      return true;
    }
    const content = `${row.execution_id} ${row.tool_id} ${row.sample_name || row.sample_id}`.toLowerCase();
    return content.includes(query);
  });

  return (
    <div className="stack-layout">
      <WorkspaceSectionHeader
        title="执行历史"
        description="按时间线性浏览执行记录，弱化卡片感，突出样本、工具和状态。"
        aside={
          <button className="control-btn" onClick={() => void onRefresh()}>
            刷新
          </button>
        }
      />
      <input
        className="control-input workspace-filter-input"
        type="text"
        placeholder="搜索 execution_id / tool / sample"
        value={historySearch}
        onChange={(event) => onHistorySearchChange(event.target.value)}
        aria-label="搜索历史"
      />

      <div className="history-linear-list">
        {visibleRows.length === 0 ? (
          <WorkspaceEmptyState
            mark="Hist"
            label="暂无执行记录"
            hint="提交任务后，新的执行状态和归档动作会按相同节奏展示在这里。"
            compact
          />
        ) : null}
        {visibleRows.map((row) => (
          <article key={row.execution_id} className="history-linear-row">
            <div className="history-linear-main">
              <div className="history-linear-title-row">
                <strong>{row.sample_name || row.sample_id || "unknown_sample"}</strong>
                <span className="badge">{row.status}</span>
              </div>
              <div className="history-linear-meta">
                <span>{row.tool_id}</span>
                <span>{row.execution_id}</span>
                <span>{row.created_at ? new Date(row.created_at * 1000).toLocaleString("zh-CN") : "unknown time"}</span>
              </div>
            </div>
            <div className="history-linear-actions">
              <button
                className="control-btn"
                disabled={busyArchiveId === row.execution_id}
                onClick={() => void onArchiveExecution(row.execution_id)}
              >
                {busyArchiveId === row.execution_id ? "归档中..." : "归档"}
              </button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

type DatabaseSectionProps = {
  databases: DatabaseEntry[];
  onRefresh: () => Promise<void>;
};

export function DatabaseSection({ databases, onRefresh }: DatabaseSectionProps) {
  return (
    <div className="stack-layout">
      <WorkspaceSectionHeader
        title="数据库状态"
        description="确认本地路径、分类和状态消息"
        aside={
          <button className="control-btn" onClick={() => void onRefresh()}>
            刷新
          </button>
        }
      />

      {databases.length === 0 ? (
        <WorkspaceEmptyState
          mark="DB"
          label="暂无数据库定义或未选择项目"
          hint="选择项目后，这里会展示已配置数据库的路径和状态。"
          compact
        />
      ) : null}

      <div className="database-linear-list">
        {databases.map((db) => (
          <article key={db.db_id} className="database-linear-row">
            <div className="database-linear-main">
              <div className="row">
                <strong>{db.name}</strong>
                <span className="badge">{db.status || "n/a"}</span>
              </div>
              <div className="database-linear-meta">
                <span>{db.db_id}</span>
                <span>{db.category}</span>
              </div>
              <div className="muted">path: {db.resolved_path || "(empty)"}</div>
            </div>
            <div className="database-linear-side">
              {db.status_message ? <div className="muted">{db.status_message}</div> : <div className="muted">状态消息为空</div>}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

type SettingsSectionProps = {
  settingsDraft: string;
  settingsBusy: boolean;
  settingsMessage: string;
  parsedSettings: SettingsPayload | null;
  sshSettings: SSHSettings;
  sshStatus: SSHStatus | null;
  sshMessage: string;
  sshBusyAction: string;
  sshDiagnostics: SSHDiagnosticStep[];
  onSettingsDraftChange: (value: string) => void;
  onReloadSettings: () => Promise<void>;
  onApplySettings: () => Promise<void>;
  onSSHFieldChange: <K extends keyof SSHSettings>(key: K, value: SSHSettings[K]) => void;
  onReloadSSHStatus: () => Promise<void>;
  onSaveSSHSettings: () => Promise<void>;
  onConnectSSH: () => Promise<void>;
  onDisconnectSSH: () => Promise<void>;
  onTestSSH: () => Promise<void>;
};

export function SettingsSection(props: SettingsSectionProps) {
  return (
    <div className="settings-layout">
      <section className="settings-column">
        <section className="settings-editor-panel">
          <WorkspaceSectionHeader
            title="SSH 连接"
            description="把远程连接、测试和断开动作从 JSON 编辑器里解耦出来"
            aside={
              <div className="settings-actions">
                <button className="control-btn" onClick={() => void props.onReloadSSHStatus()}>
                  刷新状态
                </button>
                <button
                  className="ui-button"
                  disabled={props.sshBusyAction === "test"}
                  onClick={() => {
                    void props.onTestSSH();
                  }}
                >
                  {props.sshBusyAction === "test" ? "测试中..." : "测试连接"}
                </button>
                <button
                  className="ui-button ui-button--primary"
                  disabled={props.sshBusyAction === "connect"}
                  onClick={() => {
                    void props.onConnectSSH();
                  }}
                >
                  {props.sshBusyAction === "connect" ? "连接中..." : "连接"}
                </button>
                <button
                  className="control-btn"
                  disabled={props.sshBusyAction === "disconnect"}
                  onClick={() => {
                    void props.onDisconnectSSH();
                  }}
                >
                  {props.sshBusyAction === "disconnect" ? "断开中..." : "断开"}
                </button>
              </div>
            }
          />

          <div className="settings-status-strip">
            <span className={`status-pill${props.sshStatus?.connected ? " status-pill--ok" : ""}`}>
              {props.sshStatus?.connected ? "已连接" : "未连接"}
            </span>
            <span className="badge">{props.sshStatus?.configured ? "已配置" : "未配置"}</span>
            <span className="badge">{props.sshSettings.use_key ? "密钥模式" : "密码模式"}</span>
            <span className="badge">{props.sshSettings.host || "未填写主机"}</span>
          </div>

          <div className="settings-form-grid">
            <div className="field-block">
              <label className="field-label" htmlFor="ssh-host">
                Host
              </label>
              <input
                id="ssh-host"
                className="control-input"
                value={props.sshSettings.host}
                onChange={(event) => props.onSSHFieldChange("host", event.target.value)}
                placeholder="192.168.0.152"
              />
            </div>
            <div className="field-block">
              <label className="field-label" htmlFor="ssh-port">
                Port
              </label>
              <input
                id="ssh-port"
                className="control-input"
                type="number"
                value={props.sshSettings.port}
                onChange={(event) => props.onSSHFieldChange("port", Number(event.target.value || 22))}
                placeholder="22"
              />
            </div>
            <div className="field-block">
              <label className="field-label" htmlFor="ssh-user">
                User
              </label>
              <input
                id="ssh-user"
                className="control-input"
                value={props.sshSettings.user}
                onChange={(event) => props.onSSHFieldChange("user", event.target.value)}
                placeholder="ubuntu"
              />
            </div>
            <div className="field-block">
              <label className="field-label" htmlFor="ssh-password">
                Password
              </label>
              <input
                id="ssh-password"
                className="control-input"
                type="password"
                value={props.sshSettings.password}
                onChange={(event) => props.onSSHFieldChange("password", event.target.value)}
                placeholder={props.sshSettings.use_key ? "密钥模式下可留空" : "输入 SSH 密码"}
              />
            </div>
            <div className="field-block field-block--full">
              <label className="field-label" htmlFor="ssh-key-file">
                Key File
              </label>
              <input
                id="ssh-key-file"
                className="control-input"
                value={props.sshSettings.key_file}
                onChange={(event) => props.onSSHFieldChange("key_file", event.target.value)}
                placeholder="~/.ssh/id_rsa"
              />
            </div>
            <label className="checkbox-row field-block--full" htmlFor="ssh-use-key">
              <input
                id="ssh-use-key"
                type="checkbox"
                checked={props.sshSettings.use_key}
                onChange={(event) => props.onSSHFieldChange("use_key", event.target.checked)}
              />
              <span>使用密钥连接</span>
            </label>
          </div>

          <div className="form-actions">
            <button
              className="ui-button ui-button--primary"
              disabled={props.sshBusyAction === "save"}
              onClick={() => {
                void props.onSaveSSHSettings();
              }}
            >
              {props.sshBusyAction === "save" ? "保存中..." : "保存 SSH 设置"}
            </button>
          </div>

          {props.sshMessage ? <p className="ok-text">{props.sshMessage}</p> : null}

          {props.sshDiagnostics.length > 0 ? (
            <div className="diagnostics-list">
              {props.sshDiagnostics.map((step) => (
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

        <section className="settings-editor-panel">
          <WorkspaceSectionHeader
            title="系统设置 JSON Patch"
            description="直接编辑系统设置对象并提交更新"
            aside={
              <div className="settings-actions">
                <button className="control-btn" onClick={() => void props.onReloadSettings()}>
                  重新加载
                </button>
                <button
                  className="ui-button ui-button--primary"
                  disabled={props.settingsBusy}
                  onClick={() => {
                    void props.onApplySettings();
                  }}
                >
                  {props.settingsBusy ? "提交中..." : "应用设置"}
                </button>
              </div>
            }
          />
          <textarea
            className="settings-textarea"
            value={props.settingsDraft}
            onChange={(event) => props.onSettingsDraftChange(event.target.value)}
            aria-label="settings json"
            spellCheck={false}
          />
          {props.settingsMessage ? <p className="ok-text">{props.settingsMessage}</p> : null}
        </section>
      </section>

      <SettingsPreviewPanel
        parsedSettings={props.parsedSettings}
        sshSettings={props.sshSettings}
        sshStatus={props.sshStatus}
      />
    </div>
  );
}
