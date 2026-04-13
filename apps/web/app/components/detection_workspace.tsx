"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  DatabaseSection,
  HistorySection,
  ProjectsSection,
  RunsSection,
  SettingsSection,
} from "./detection_workspace_sections";
import { DetectionWorkspaceProjectSelect } from "./detection_workspace_project_select";
import { DetectionWorkspaceShell } from "./detection_workspace_shell";
import type {
  DatabaseEntry,
  Execution,
  Project,
  SettingsPayload,
  SSHDiagnosticStep,
  SSHSettings,
  SSHStatus,
  TabId,
  ToolDescriptor,
  ToolSummary,
} from "./detection_workspace_types";
import {
  apiBase,
  defaultSSHSettings,
  isRecord,
  parseSSHDiagnosticSteps,
  parseSSHSettings,
  parseSSHStatus,
  parseSettingsPayload,
  prettyJson,
  readJsonOrThrow,
  safeText,
  toDatabaseEntry,
  toExecution,
  toProject,
  toToolSummary,
} from "./detection_workspace_utils";
import { useDetectionWorkspaceHotkeys } from "./use_detection_workspace_hotkeys";
import { WorkbenchPanel } from "./workbench_panel";

export function DetectionWorkspace({ activeTab }: { activeTab: TabId }) {
  const router = useRouter();

  const [projects, setProjects] = useState<Project[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState<string>("");
  const [historyRows, setHistoryRows] = useState<Execution[]>([]);
  const [databases, setDatabases] = useState<DatabaseEntry[]>([]);
  const [tools, setTools] = useState<ToolSummary[]>([]);

  const [selectedToolId, setSelectedToolId] = useState<string>("");
  const [selectedDescriptor, setSelectedDescriptor] = useState<ToolDescriptor | null>(null);
  const [toolSearch, setToolSearch] = useState<string>("");
  const [historySearch, setHistorySearch] = useState<string>("");
  const [toolRunMsg, setToolRunMsg] = useState<string>("");
  const [toolRunBusy, setToolRunBusy] = useState<boolean>(false);
  const [busyArchiveId, setBusyArchiveId] = useState<string>("");

  const [settingsDraft, setSettingsDraft] = useState<string>("{}");
  const [settingsValue, setSettingsValue] = useState<SettingsPayload | null>(null);
  const [settingsBusy, setSettingsBusy] = useState<boolean>(false);
  const [settingsMessage, setSettingsMessage] = useState<string>("");
  const [sshSettings, setSSHSettings] = useState<SSHSettings>(defaultSSHSettings());
  const [sshStatus, setSSHStatus] = useState<SSHStatus | null>(null);
  const [sshDiagnostics, setSSHDiagnostics] = useState<SSHDiagnosticStep[]>([]);
  const [sshBusyAction, setSSHBusyAction] = useState<string>("");
  const [sshMessage, setSSHMessage] = useState<string>("");

  const [createProjectName, setCreateProjectName] = useState<string>("");
  const [createProjectDescription, setCreateProjectDescription] = useState<string>("");
  const [createProjectBusy, setCreateProjectBusy] = useState<boolean>(false);
  const [createProjectMessage, setCreateProjectMessage] = useState<string>("");

  const [error, setError] = useState<string>("");

  const currentProject = useMemo(
    () => projects.find((project) => project.project_id === currentProjectId),
    [projects, currentProjectId]
  );

  const filteredTools = useMemo(() => {
    const query = toolSearch.trim().toLowerCase();
    if (!query) {
      return tools;
    }
    return tools.filter((tool) => {
      const content = `${tool.id} ${tool.name} ${tool.category} ${tool.description}`.toLowerCase();
      return content.includes(query);
    });
  }, [toolSearch, tools]);

  const syncSSHSettingsFromPayload = (payload: SettingsPayload | null) => {
    const sshValue = isRecord(payload) ? payload.ssh : null;
    setSSHSettings(parseSSHSettings(sshValue));
  };

  const refreshSSHStatus = async () => {
    const resp = await fetch(`${apiBase()}/api/v1/ssh/status`);
    const data = await readJsonOrThrow(resp);
    setSSHStatus(parseSSHStatus(data?.item));
  };

  const refreshSettings = async () => {
    const resp = await fetch(`${apiBase()}/api/v1/settings`);
    const data = await readJsonOrThrow(resp);
    const payload = parseSettingsPayload(data?.item);
    setSettingsValue(payload);
    setSettingsDraft(prettyJson(payload));
    syncSSHSettingsFromPayload(payload);
  };

  const applySettings = async () => {
    setSettingsMessage("");
    setError("");
    setSettingsBusy(true);
    try {
      const parsed = JSON.parse(settingsDraft);
      if (!isRecord(parsed)) {
        throw new Error("settings patch must be a JSON object");
      }
      const resp = await fetch(`${apiBase()}/api/v1/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ patch: parsed }),
      });
      const data = await readJsonOrThrow(resp);
      const payload = parseSettingsPayload(data?.item);
      setSettingsValue(payload);
      setSettingsDraft(prettyJson(payload));
      syncSSHSettingsFromPayload(payload);
      setSettingsMessage("设置已更新");
      await refreshSSHStatus();
      if (currentProjectId) {
        await refreshDatabases(currentProjectId);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setSettingsBusy(false);
    }
  };

  const createProject = async () => {
    const name = createProjectName.trim();
    if (!name) {
      setError("项目名称不能为空。");
      return;
    }

    setError("");
    setCreateProjectMessage("");
    setCreateProjectBusy(true);
    try {
      const resp = await fetch(`${apiBase()}/api/v1/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          description: createProjectDescription.trim() || undefined,
          open_after_create: true,
        }),
      });
      const data = await readJsonOrThrow(resp);
      const createdId = safeText(data?.item?.project_id);
      setCreateProjectName("");
      setCreateProjectDescription("");
      setCreateProjectMessage(createdId ? `项目已创建并打开: ${createdId}` : "项目已创建并打开");
      await refreshProjects();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setCreateProjectBusy(false);
    }
  };

  const refreshProjects = async () => {
    const projectResp = await fetch(`${apiBase()}/api/v1/projects`);
    const projectData = (await readJsonOrThrow(projectResp)) as { items?: unknown[] };
    const projectItems: Project[] = Array.isArray(projectData.items)
      ? projectData.items.map(toProject).filter((item: Project | null): item is Project => !!item)
      : [];
    setProjects(projectItems);

    const currentResp = await fetch(`${apiBase()}/api/v1/projects/current`);
    const currentData = (await readJsonOrThrow(currentResp)) as { item?: Record<string, unknown> };
    const pid = safeText(currentData?.item?.project_id) || projectItems[0]?.project_id || "";
    if (pid) {
      await openProject(pid);
    } else {
      setCurrentProjectId("");
    }
  };

  const openProject = async (projectId: string) => {
    const normalizedProjectId = safeText(projectId);
    if (!normalizedProjectId) {
      setCurrentProjectId("");
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(normalizedProjectId)}/open`, {
      method: "POST",
    });
    await readJsonOrThrow(resp);
    setCurrentProjectId(normalizedProjectId);
  };

  const refreshHistory = async (projectId: string) => {
    if (!projectId) {
      setHistoryRows([]);
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/history?limit=50`);
    const data = (await readJsonOrThrow(resp)) as { items?: unknown[] };
    const items: Execution[] = Array.isArray(data.items)
      ? data.items.map(toExecution).filter((item: Execution | null): item is Execution => !!item)
      : [];
    setHistoryRows(items);
  };

  const refreshDatabases = async (projectId: string) => {
    if (!projectId) {
      setDatabases([]);
      return;
    }
    const resp = await fetch(
      `${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/databases?include_status=true`
    );
    const data = (await readJsonOrThrow(resp)) as { items?: unknown[] };
    const items: DatabaseEntry[] = Array.isArray(data.items)
      ? data.items
          .map(toDatabaseEntry)
          .filter((item: DatabaseEntry | null): item is DatabaseEntry => !!item)
      : [];
    setDatabases(items);
  };

  const refreshTools = async () => {
    const resp = await fetch(`${apiBase()}/api/v1/tools`);
    const data = (await readJsonOrThrow(resp)) as { items?: unknown[] };
    const items: ToolSummary[] = Array.isArray(data.items)
      ? data.items.map(toToolSummary).filter((item: ToolSummary | null): item is ToolSummary => !!item)
      : [];
    setTools(items);
    if (items.length > 0 && !selectedToolId) {
      await selectTool(items[0].id);
    }
  };

  const selectTool = async (toolId: string) => {
    const normalized = safeText(toolId);
    if (!normalized) {
      return;
    }
    setSelectedToolId(normalized);
    const resp = await fetch(`${apiBase()}/api/v1/tools/${encodeURIComponent(normalized)}/descriptor`);
    const data = (await readJsonOrThrow(resp)) as { item?: unknown };
    const item = data?.item;
    if (isRecord(item)) {
      setSelectedDescriptor(item as ToolDescriptor);
    } else {
      setSelectedDescriptor(null);
    }
  };

  const runSelectedTool = async (params: Record<string, unknown>) => {
    void params;
    setError("");
    setToolRunMsg("旧工具运行入口已禁用。请改到 /workspace 通过 workflow/run 主线提交新执行。");
  };

  const archiveExecution = async (executionId: string) => {
    if (!currentProjectId) {
      return;
    }
    setBusyArchiveId(executionId);
    setError("");
    try {
      const resp = await fetch(
        `${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/executions/${encodeURIComponent(
          executionId
        )}/archive`,
        { method: "POST" }
      );
      await readJsonOrThrow(resp);
      await refreshHistory(currentProjectId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setBusyArchiveId("");
    }
  };

  const saveSSHSettings = async () => {
    setError("");
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
      setSettingsValue(payload);
      setSettingsDraft(prettyJson(payload));
      syncSSHSettingsFromPayload(payload);
      setSSHMessage("SSH 设置已保存");
      await refreshSSHStatus();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setSSHBusyAction("");
    }
  };

  const connectSSH = async () => {
    setError("");
    setSSHMessage("");
    setSSHBusyAction("connect");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/ssh/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          host: sshSettings.host,
          port: sshSettings.port,
          user: sshSettings.user,
          password: sshSettings.password,
          use_key: sshSettings.use_key,
          key_file: sshSettings.key_file,
        }),
      });
      const data = await readJsonOrThrow(resp);
      setSSHStatus(parseSSHStatus(data?.item));
      setSSHDiagnostics([]);
      setSSHMessage(safeText(data?.item?.message, "SSH 已连接"));
      if (currentProjectId) {
        await refreshDatabases(currentProjectId);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setSSHBusyAction("");
    }
  };

  const disconnectSSH = async () => {
    setError("");
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
      if (currentProjectId) {
        await refreshDatabases(currentProjectId);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setSSHBusyAction("");
    }
  };

  const testSSH = async () => {
    setError("");
    setSSHMessage("");
    setSSHBusyAction("test");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/ssh/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          host: sshSettings.host,
          port: sshSettings.port,
          user: sshSettings.user,
          password: sshSettings.password,
          use_key: sshSettings.use_key,
          key_file: sshSettings.key_file,
        }),
      });
      const data = await readJsonOrThrow(resp);
      setSSHDiagnostics(parseSSHDiagnosticSteps(data?.item?.steps));
      setSSHStatus(parseSSHStatus(data?.item?.status));
      setSSHMessage(safeText(data?.item?.message));
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setSSHBusyAction("");
    }
  };

  useEffect(() => {
    const run = async () => {
      try {
        await refreshProjects();
        await refreshTools();
        await refreshSettings();
        await refreshSSHStatus();
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
      }
    };
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const run = async () => {
      if (!currentProjectId) {
        setHistoryRows([]);
        setDatabases([]);
        return;
      }
      try {
        await refreshHistory(currentProjectId);
        await refreshDatabases(currentProjectId);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
      }
    };
    void run();
  }, [currentProjectId]);

  useDetectionWorkspaceHotkeys(router);

  return (
    <DetectionWorkspaceShell
      activeTab={activeTab}
      currentProject={currentProject}
      currentProjectId={currentProjectId}
      projects={projects}
      toolsCount={tools.length}
      historyCount={historyRows.length}
      databasesCount={databases.length}
      error={error}
      projectSelect={
        <DetectionWorkspaceProjectSelect
          currentProjectId={currentProjectId}
          projects={projects}
          onOpenProject={openProject}
        />
      }
      onRefreshProjects={() => {
        void refreshProjects();
      }}
    >
      {activeTab === "projects" ? (
            <ProjectsSection
              projects={projects}
              currentProjectId={currentProjectId}
              onOpenProject={openProject}
              onRefreshProjects={refreshProjects}
              createProjectName={createProjectName}
              createProjectDescription={createProjectDescription}
              createProjectBusy={createProjectBusy}
              createProjectMessage={createProjectMessage}
              onChangeCreateProjectName={setCreateProjectName}
              onChangeCreateProjectDescription={setCreateProjectDescription}
              onCreateProject={createProject}
            />
      ) : null}

      {activeTab === "runs" ? (
            <RunsSection
              filteredTools={filteredTools}
              selectedToolId={selectedToolId}
              selectedDescriptor={selectedDescriptor}
              toolSearch={toolSearch}
              onToolSearchChange={setToolSearch}
              onSelectTool={selectTool}
              toolRunBusy={toolRunBusy}
              onRunTool={runSelectedTool}
              toolRunMsg={toolRunMsg}
              toolRunHint="旧工具执行已停用；请前往 /workspace，通过 workflow compile + run 提交新的分析任务。"
            />
      ) : null}

      {activeTab === "history" ? (
            <HistorySection
              historyRows={historyRows}
              historySearch={historySearch}
              busyArchiveId={busyArchiveId}
              onHistorySearchChange={setHistorySearch}
              onRefresh={async () => {
                await refreshHistory(currentProjectId);
              }}
              onArchiveExecution={archiveExecution}
            />
      ) : null}

      {activeTab === "databases" ? (
            <DatabaseSection
              databases={databases}
              onRefresh={async () => {
                await refreshDatabases(currentProjectId);
              }}
            />
      ) : null}

      {activeTab === "settings" ? (
            <SettingsSection
              settingsDraft={settingsDraft}
              settingsBusy={settingsBusy}
              settingsMessage={settingsMessage}
              parsedSettings={settingsValue}
              sshSettings={sshSettings}
              sshStatus={sshStatus}
              sshMessage={sshMessage}
              sshBusyAction={sshBusyAction}
              sshDiagnostics={sshDiagnostics}
              onSettingsDraftChange={setSettingsDraft}
              onReloadSettings={refreshSettings}
              onApplySettings={applySettings}
              onSSHFieldChange={(key, value) => {
                setSSHSettings((prev) => ({ ...prev, [key]: value }));
              }}
              onReloadSSHStatus={refreshSSHStatus}
              onSaveSSHSettings={saveSSHSettings}
              onConnectSSH={connectSSH}
              onDisconnectSSH={disconnectSSH}
              onTestSSH={testSSH}
            />
      ) : null}

      {activeTab === "workbench" ? (
            <WorkbenchPanel
              currentProjectId={currentProjectId}
              onError={setError}
              onAfterRun={async () => {
                await refreshHistory(currentProjectId);
              }}
            />
      ) : null}
    </DetectionWorkspaceShell>
  );
}
