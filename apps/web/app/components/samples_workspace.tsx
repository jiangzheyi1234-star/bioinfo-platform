"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { DetectionWorkspaceProjectSelect } from "./detection_workspace_project_select";
import { DetectionWorkspaceShell } from "./detection_workspace_shell";
import type { Project, Sample } from "./detection_workspace_types";
import {
  apiBase,
  isRecord,
  prettyJson,
  readJsonOrThrow,
  safeText,
  toProject,
  toSample,
  toToolSummary,
} from "./detection_workspace_utils";
import { useDetectionWorkspaceHotkeys } from "./use_detection_workspace_hotkeys";
import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";

export function SamplesWorkspace() {
  const router = useRouter();

  const [projects, setProjects] = useState<Project[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState<string>("");
  const [samples, setSamples] = useState<Sample[]>([]);
  const [sampleSearch, setSampleSearch] = useState<string>("");
  const [selectedSampleId, setSelectedSampleId] = useState<string>("");
  const [sampleName, setSampleName] = useState<string>("");
  const [sampleSource, setSampleSource] = useState<string>("");
  const [sampleMetadata, setSampleMetadata] = useState<string>('{\n  "batch": ""\n}');
  const [createBusy, setCreateBusy] = useState<boolean>(false);
  const [message, setMessage] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [toolsCount, setToolsCount] = useState<number>(0);
  const [historyCount, setHistoryCount] = useState<number>(0);
  const [databasesCount, setDatabasesCount] = useState<number>(0);

  const currentProject = useMemo(
    () => projects.find((project) => project.project_id === currentProjectId),
    [projects, currentProjectId]
  );

  const visibleSamples = useMemo(() => {
    const query = sampleSearch.trim().toLowerCase();
    if (!query) {
      return samples;
    }
    return samples.filter((sample) => {
      const content = `${sample.sample_id} ${sample.name} ${sample.source || ""}`.toLowerCase();
      return content.includes(query);
    });
  }, [sampleSearch, samples]);

  const selectedSample = useMemo(
    () => visibleSamples.find((sample) => sample.sample_id === selectedSampleId) ?? samples.find((sample) => sample.sample_id === selectedSampleId) ?? null,
    [samples, selectedSampleId, visibleSamples]
  );

  const refreshToolsCount = async () => {
    const resp = await fetch(`${apiBase()}/api/v1/tools`);
    const data = (await readJsonOrThrow(resp)) as { items?: unknown[] };
    const items = Array.isArray(data.items)
      ? data.items.map(toToolSummary).filter((item): item is NonNullable<typeof item> => !!item)
      : [];
    setToolsCount(items.length);
  };

  const refreshSamples = async (projectId: string) => {
    if (!projectId) {
      setSamples([]);
      setSelectedSampleId("");
      setHistoryCount(0);
      setDatabasesCount(0);
      return;
    }

    const [samplesResp, historyResp, databasesResp] = await Promise.all([
      fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/samples`),
      fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/history?limit=50`),
      fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/databases?include_status=true`),
    ]);

    const samplesData = (await readJsonOrThrow(samplesResp)) as { items?: unknown[] };
    const historyData = (await readJsonOrThrow(historyResp)) as { items?: unknown[] };
    const databasesData = (await readJsonOrThrow(databasesResp)) as { items?: unknown[] };

    const nextSamples = Array.isArray(samplesData.items)
      ? samplesData.items.map(toSample).filter((item: Sample | null): item is Sample => !!item)
      : [];
    setSamples(nextSamples);
    setHistoryCount(Array.isArray(historyData.items) ? historyData.items.length : 0);
    setDatabasesCount(Array.isArray(databasesData.items) ? databasesData.items.length : 0);
    setSelectedSampleId((prev) => {
      if (prev && nextSamples.some((sample) => sample.sample_id === prev)) {
        return prev;
      }
      return nextSamples[0]?.sample_id || "";
    });
  };

  const openProject = async (projectId: string) => {
    const normalizedProjectId = safeText(projectId);
    if (!normalizedProjectId) {
      setCurrentProjectId("");
      setSamples([]);
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(normalizedProjectId)}/open`, {
      method: "POST",
    });
    await readJsonOrThrow(resp);
    setCurrentProjectId(normalizedProjectId);
    await refreshSamples(normalizedProjectId);
  };

  const refreshProjects = async () => {
    const projectResp = await fetch(`${apiBase()}/api/v1/projects`);
    const projectData = (await readJsonOrThrow(projectResp)) as { items?: unknown[] };
    const items = Array.isArray(projectData.items)
      ? projectData.items.map(toProject).filter((item: Project | null): item is Project => !!item)
      : [];
    setProjects(items);

    const currentResp = await fetch(`${apiBase()}/api/v1/projects/current`);
    const currentData = (await readJsonOrThrow(currentResp)) as { item?: Record<string, unknown> };
    const currentId = safeText(currentData?.item?.project_id) || items[0]?.project_id || "";
    if (currentId) {
      await openProject(currentId);
    } else {
      setCurrentProjectId("");
      setSamples([]);
    }
  };

  const createSample = async () => {
    if (!currentProjectId) {
      setError("请先选择项目。");
      return;
    }
    const trimmedName = sampleName.trim();
    if (!trimmedName) {
      setError("样本名称不能为空。");
      return;
    }

    setCreateBusy(true);
    setError("");
    setMessage("");
    try {
      const parsedMetadata = sampleMetadata.trim() ? JSON.parse(sampleMetadata) : {};
      if (!isRecord(parsedMetadata)) {
        throw new Error("sample metadata must be a JSON object");
      }
      const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/samples`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: trimmedName,
          source: sampleSource.trim() || undefined,
          metadata: parsedMetadata,
        }),
      });
      const data = await readJsonOrThrow(resp);
      const createdId = safeText(data?.item?.sample_id);
      setSampleName("");
      setSampleSource("");
      setMessage(createdId ? `样本已创建: ${createdId}` : "样本已创建");
      await refreshSamples(currentProjectId);
      if (createdId) {
        setSelectedSampleId(createdId);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreateBusy(false);
    }
  };

  useEffect(() => {
    const run = async () => {
      try {
        await Promise.all([refreshProjects(), refreshToolsCount()]);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    };
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useDetectionWorkspaceHotkeys(router);

  return (
    <DetectionWorkspaceShell
      activeTab="samples"
      currentProject={currentProject}
      currentProjectId={currentProjectId}
      projects={projects}
      toolsCount={toolsCount}
      historyCount={historyCount}
      databasesCount={databasesCount}
      error={error}
      projectSelect={
        <DetectionWorkspaceProjectSelect
          currentProjectId={currentProjectId}
          projects={projects}
          onOpenProject={openProject}
        />
      }
      onRefreshProjects={() => refreshProjects()}
    >
      <div className="samples-layout">
        <section className="samples-list-panel workspace-panel-card">
          <WorkspaceSectionHeader
            title="样本列表"
            description="按项目维度维护样本名称、来源和元数据。"
            aside={<span className="badge">{visibleSamples.length}</span>}
          />
          <input
            className="control-input workspace-filter-input"
            value={sampleSearch}
            onChange={(event) => setSampleSearch(event.target.value)}
            placeholder="搜索 sample_id / name / source"
            aria-label="搜索样本"
          />
          <div className="samples-list">
            {!currentProjectId ? (
              <WorkspaceEmptyState
                mark="Sample"
                label="尚未选择项目"
                hint="先切换或创建项目，再加载当前项目的样本清单。"
                compact
              />
            ) : null}
            {currentProjectId && visibleSamples.length === 0 ? (
              <WorkspaceEmptyState
                mark="Sample"
                label="当前项目暂无样本"
                hint="右侧创建第一个样本后，这里会保持列表和详情联动。"
                compact
              />
            ) : null}
            {visibleSamples.map((sample) => {
              const active = sample.sample_id === selectedSampleId;
              return (
                <button
                  key={sample.sample_id}
                  type="button"
                  className={`sample-list-item${active ? " active" : ""}`}
                  onClick={() => setSelectedSampleId(sample.sample_id)}
                >
                  <div className="sample-list-title-row">
                    <strong>{sample.name}</strong>
                    <span className="badge">{sample.source || "unspecified"}</span>
                  </div>
                  <div className="muted">{sample.sample_id}</div>
                </button>
              );
            })}
          </div>
        </section>

        <section className="samples-detail-panel workspace-panel-card">
          <WorkspaceSectionHeader
            title={selectedSample ? selectedSample.name : "创建样本"}
            description={selectedSample ? "查看当前样本的来源和 metadata。" : "在当前项目下新增样本记录。"}
          />

          {selectedSample ? (
            <div className="sample-detail-stack">
              <div className="sample-meta-grid">
                <div className="sample-meta-card">
                  <span className="sample-meta-label">Sample ID</span>
                  <code>{selectedSample.sample_id}</code>
                </div>
                <div className="sample-meta-card">
                  <span className="sample-meta-label">Source</span>
                  <strong>{selectedSample.source || "unspecified"}</strong>
                </div>
              </div>
              <div className="workspace-json-surface">
                <div className="split-title">Metadata</div>
                <pre className="json-preview">{prettyJson(selectedSample.metadata)}</pre>
              </div>
            </div>
          ) : (
            <WorkspaceEmptyState
              mark="Meta"
              label="未选中样本"
              hint="从左侧列表选择样本，或直接在下方创建新样本。"
              compact
            />
          )}

          <div className="sample-create-form">
            <div className="split-title">新建样本</div>
            <div className="field-block">
              <label className="field-label" htmlFor="sample-name">
                Name
              </label>
              <input
                id="sample-name"
                className="control-input"
                value={sampleName}
                onChange={(event) => setSampleName(event.target.value)}
                placeholder="例如：MGX_2026_04_001"
              />
            </div>
            <div className="field-block">
              <label className="field-label" htmlFor="sample-source">
                Source
              </label>
              <input
                id="sample-source"
                className="control-input"
                value={sampleSource}
                onChange={(event) => setSampleSource(event.target.value)}
                placeholder="例如：serum / soil / water"
              />
            </div>
            <div className="field-block">
              <label className="field-label" htmlFor="sample-metadata">
                Metadata JSON
              </label>
              <textarea
                id="sample-metadata"
                className="input-control textarea-control"
                value={sampleMetadata}
                onChange={(event) => setSampleMetadata(event.target.value)}
                spellCheck={false}
              />
            </div>
            <div className="form-actions">
              <button className="ui-button ui-button--primary" disabled={createBusy || !currentProjectId} onClick={() => void createSample()}>
                {createBusy ? "创建中..." : "创建样本"}
              </button>
            </div>
            {message ? <p className="ok-text">{message}</p> : null}
          </div>
        </section>
      </div>
    </DetectionWorkspaceShell>
  );
}
