import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Loader2, RefreshCw, SendHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import { GENERATED_TOOL_RUN_PIPELINE_ID } from "./generated-workflow-model";
import { submitToolProductionEvidence, type ToolProductionEvidencePayload } from "./tools-page-api";
import {
  type ToolCatalogProductionQueue,
  type ToolCatalogProductionQueueItem,
  toolErrorMessage,
} from "./tools-page-model";
import { fetchRunsList, fetchWorkflowRunDetail } from "./workflows-page-api";
import type { WorkflowArtifact, WorkflowRun, WorkflowRunDetail } from "./workflows-page-model";

const MANUAL_RUN_VALUE = "__manual__";
const ANY_ARTIFACT_VALUE = "__any__";
const DEFAULT_EVIDENCE_TYPE = "real-data-acceptance";
const DEFAULT_TARGET_PLATFORM = "linux-64";
const DEFAULT_POLICY_VERSION = "tool-production-policy-v1";

type ProductionEvidenceForm = {
  evidenceType: string;
  message: string;
  artifactId: string;
  artifactName: string;
  artifactDigest: string;
  logPath: string;
  targetPlatform: string;
  policyVersion: string;
  databaseId: string;
  templateId: string;
  role: string;
  packId: string;
  packChecksum: string;
};

export function ToolProductionEvidencePanel({
  productionQueue,
  onQueueChanged,
}: {
  productionQueue?: ToolCatalogProductionQueue;
  onQueueChanged?: () => Promise<void> | void;
}) {
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState("");
  const [selectedRunId, setSelectedRunId] = useState(MANUAL_RUN_VALUE);
  const [manualRunId, setManualRunId] = useState("");
  const [runDetail, setRunDetail] = useState<WorkflowRunDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [forms, setForms] = useState<Record<string, Partial<ProductionEvidenceForm>>>({});
  const [itemErrors, setItemErrors] = useState<Record<string, string>>({});
  const [submittingToolId, setSubmittingToolId] = useState("");
  const [completedToolId, setCompletedToolId] = useState("");
  const [visibleLimit, setVisibleLimit] = useState(3);

  const loadRuns = useCallback(async () => {
    setRunsLoading(true);
    setRunsError("");
    try {
      const items = await fetchRunsList({ forceRefresh: true });
      setRuns(items);
    } catch (err) {
      setRunsError(toolErrorMessage(err, "读取生产证据运行记录失败"));
    } finally {
      setRunsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  const runCandidates = useMemo(() => {
    return runs.filter(isCompletedGeneratedToolRun).sort((left, right) => runTime(right) - runTime(left)).slice(0, 20);
  }, [runs]);

  useEffect(() => {
    if (selectedRunId !== MANUAL_RUN_VALUE || manualRunId.trim() || runCandidates.length === 0) return;
    setSelectedRunId(runCandidates[0].runId);
  }, [manualRunId, runCandidates, selectedRunId]);

  const activeRunId = selectedRunId === MANUAL_RUN_VALUE ? manualRunId.trim() : selectedRunId;

  useEffect(() => {
    let cancelled = false;
    const normalizedRunId = activeRunId.trim();
    setRunDetail(null);
    setDetailError("");
    if (!normalizedRunId) {
      setDetailLoading(false);
      return;
    }
    setDetailLoading(true);
    void fetchWorkflowRunDetail(normalizedRunId)
      .then((detail) => {
        if (!cancelled) setRunDetail(detail);
      })
      .catch((err) => {
        if (!cancelled) setDetailError(toolErrorMessage(err, "读取运行详情失败"));
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeRunId]);

  const items = productionQueue?.items ?? [];
  if (!items.length) return null;

  const visibleItems = items.slice(0, visibleLimit);
  const hiddenItemCount = Math.max(0, items.length - visibleItems.length);
  const artifacts = runDetail?.results?.artifacts ?? [];
  const activeRun = runDetail?.run ?? runCandidates.find((run) => run.runId === activeRunId);
  const runDetailReady = Boolean(activeRunId && runDetail && !detailLoading && !detailError);

  async function submitEvidence(item: ToolCatalogProductionQueueItem) {
    const form = formForItem(forms, item);
    const missing = missingSubmitField(form, activeRunId, runDetailReady);
    if (missing) {
      setItemErrors((current) => ({ ...current, [item.toolId]: `${missing} 必填` }));
      return;
    }
    const selectedArtifact = selectedArtifactForForm(artifacts, form);
    setSubmittingToolId(item.toolId);
    setItemErrors((current) => ({ ...current, [item.toolId]: "" }));
    setCompletedToolId("");
    try {
      await submitToolProductionEvidence(item.toolId, buildProductionEvidencePayload({
        activeRun,
        artifact: selectedArtifact,
        form,
        runId: activeRunId,
      }));
      setCompletedToolId(item.toolId);
      await onQueueChanged?.();
      await loadRuns();
    } catch (err) {
      setItemErrors((current) => ({ ...current, [item.toolId]: toolErrorMessage(err, "提交生产证据失败") }));
    } finally {
      setSubmittingToolId((current) => current === item.toolId ? "" : current);
    }
  }

  return (
    <div
      aria-label="production evidence queue"
      data-action="submit-production-evidence"
      className="mt-3 rounded-md border border-emerald-100 bg-white px-3 py-2"
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex min-w-0 items-center gap-2">
          <span className="font-medium text-emerald-800">生产证据</span>
          <span className="text-slate-500">{productionQueue?.available ?? items.length} 可提交 · {productionQueue?.remaining ?? 0} 待处理</span>
        </div>
        <Button type="button" variant="outline" className="h-7 bg-white px-2 text-[11px]" disabled={runsLoading} onClick={() => void loadRuns()}>
          <RefreshCw strokeWidth={1.5} className={runsLoading ? "mr-1 h-3 w-3 animate-spin" : "mr-1 h-3 w-3"} />
          刷新运行
        </Button>
      </div>

      <div className="grid gap-2 rounded-md border border-slate-100 bg-slate-50 px-2 py-2 md:grid-cols-[minmax(0,1fr)_minmax(180px,0.7fr)]">
        <Select value={selectedRunId} onValueChange={setSelectedRunId}>
          <SelectTrigger className="h-8 bg-white text-xs">
            <SelectValue placeholder="选择运行" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={MANUAL_RUN_VALUE}>手动输入 runId</SelectItem>
            {runCandidates.map((run) => (
              <SelectItem key={run.runId} value={run.runId}>
                {runLabel(run)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {selectedRunId === MANUAL_RUN_VALUE ? (
          <Input
            value={manualRunId}
            onChange={(event) => setManualRunId(event.target.value)}
            className="h-8 font-mono text-xs"
            placeholder="run_real_data"
          />
        ) : (
          <div className="min-w-0 truncate px-1 pt-1 text-[11px] text-slate-500">
            {detailLoading ? "读取详情中" : runDetailSummary(runDetail, artifacts)}
          </div>
        )}
      </div>
      {runsError ? <div className="mt-1 text-[11px] text-red-600">{runsError}</div> : null}
      {detailError ? <div className="mt-1 text-[11px] text-amber-700">{detailError}</div> : null}

      <div className="mt-2 grid gap-2">
        {visibleItems.map((item) => {
          const form = formForItem(forms, item);
          const databaseEvidence = form.evidenceType === "real-database-acceptance";
          const selectedArtifact = selectedArtifactForForm(artifacts, form);
          const missing = missingSubmitField(form, activeRunId, runDetailReady);
          const submitting = submittingToolId === item.toolId;
          const completed = completedToolId === item.toolId;
          return (
            <div key={item.toolId} className="rounded-md border border-slate-100 px-2 py-2">
              <div className="mb-2 flex min-w-0 flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-xs font-medium text-slate-900">{item.toolName || item.toolId}</div>
                  <div className="mt-0.5 truncate font-mono text-[11px] text-slate-500">{item.toolRevisionId || item.toolId}</div>
                </div>
                <span className="shrink-0 text-[11px] text-slate-500">
                  <span className="font-mono text-emerald-700">{item.currentState}</span> → {item.requiredState}
                </span>
              </div>
              <div className="grid gap-2 lg:grid-cols-[170px_minmax(0,1fr)_minmax(180px,0.8fr)]">
                <Select value={form.evidenceType} onValueChange={(value) => updateEvidenceType(item.toolId, value, activeRun)}>
                  <SelectTrigger className="h-8 bg-white text-xs">
                    <SelectValue placeholder="证据类型" />
                  </SelectTrigger>
                  <SelectContent>
                    {evidenceTypesForItem(item).map((type) => (
                      <SelectItem key={type} value={type}>{type}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Input
                  value={form.message}
                  onChange={(event) => setFormField(item.toolId, "message", event.target.value)}
                  className="h-8 text-xs"
                  placeholder="Accepted against real remote data."
                  data-field="production-evidence-message"
                />
                <Select value={form.artifactId || ANY_ARTIFACT_VALUE} onValueChange={(value) => {
                  setFormPatch(item.toolId, {
                    artifactId: value === ANY_ARTIFACT_VALUE ? "" : value,
                    artifactName: "",
                  });
                }}>
                  <SelectTrigger className="h-8 bg-white text-xs" data-field="production-evidence-artifact">
                    <SelectValue placeholder="产物" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ANY_ARTIFACT_VALUE}>全部产物</SelectItem>
                    {artifacts.map((artifact) => (
                      <SelectItem key={artifact.artifactId} value={artifact.artifactId}>
                        {artifactLabel(artifact)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="mt-2 grid gap-2 md:grid-cols-4">
                <Input
                  value={form.targetPlatform}
                  onChange={(event) => setFormField(item.toolId, "targetPlatform", event.target.value)}
                  className="h-8 font-mono text-xs"
                  placeholder="linux-64"
                />
                <Input
                  value={form.policyVersion}
                  onChange={(event) => setFormField(item.toolId, "policyVersion", event.target.value)}
                  className="h-8 font-mono text-xs"
                  placeholder="tool-production-policy-v1"
                />
                <Input
                  value={form.artifactDigest || artifactDigest(selectedArtifact)}
                  onChange={(event) => setFormField(item.toolId, "artifactDigest", event.target.value)}
                  className="h-8 font-mono text-xs"
                  placeholder="sha256:..."
                />
                <Input
                  value={form.logPath}
                  onChange={(event) => setFormField(item.toolId, "logPath", event.target.value)}
                  className="h-8 font-mono text-xs"
                  placeholder="/remote/logs/run.log"
                />
              </div>
              {databaseEvidence ? (
                <div className="mt-2 grid gap-2 md:grid-cols-5">
                  <Input value={form.databaseId} onChange={(event) => setFormField(item.toolId, "databaseId", event.target.value)} className="h-8 font-mono text-xs" placeholder="databaseId" />
                  <Input value={form.templateId} onChange={(event) => setFormField(item.toolId, "templateId", event.target.value)} className="h-8 font-mono text-xs" placeholder="templateId" />
                  <Input value={form.role} onChange={(event) => setFormField(item.toolId, "role", event.target.value)} className="h-8 font-mono text-xs" placeholder="role" />
                  <Input value={form.packId} onChange={(event) => setFormField(item.toolId, "packId", event.target.value)} className="h-8 font-mono text-xs" placeholder="packId" />
                  <Input value={form.packChecksum} onChange={(event) => setFormField(item.toolId, "packChecksum", event.target.value)} className="h-8 font-mono text-xs" placeholder="packChecksum" />
                </div>
              ) : null}
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0 text-[11px] text-slate-500">
                  {itemErrors[item.toolId] ? <span className="text-red-600">{itemErrors[item.toolId]}</span> : evidenceScopeSummary(activeRun, artifacts)}
                </div>
                <Button
                  type="button"
                  variant={completed ? "outline" : "default"}
                  className="h-8 px-2.5 text-xs"
                  disabled={submitting || Boolean(missing)}
                  title={missing ? `${missing} 必填` : ""}
                  onClick={() => void submitEvidence(item)}
                >
                  {submitting ? <Loader2 strokeWidth={1.5} className="mr-1 h-3.5 w-3.5 animate-spin" /> : completed ? <CheckCircle2 strokeWidth={1.5} className="mr-1 h-3.5 w-3.5 text-emerald-600" /> : <SendHorizontal strokeWidth={1.5} className="mr-1 h-3.5 w-3.5" />}
                  {completed ? "已提交" : "提交证据"}
                </Button>
              </div>
            </div>
          );
        })}
      </div>
      {hiddenItemCount > 0 || visibleLimit > 3 ? (
        <button
          type="button"
          className="mt-1 text-[11px] font-medium text-blue-700 hover:text-blue-900"
          onClick={() => setVisibleLimit((current) => (hiddenItemCount > 0 ? current + 3 : 3))}
        >
          {hiddenItemCount > 0 ? `再显示 3 个 · 还有 ${hiddenItemCount} 个` : "收起生产证据"}
        </button>
      ) : null}
    </div>
  );

  function setFormField(toolId: string, field: keyof ProductionEvidenceForm, value: string) {
    setFormPatch(toolId, { [field]: value });
  }

  function setFormPatch(toolId: string, patch: Partial<ProductionEvidenceForm>) {
    setForms((current) => ({
      ...current,
      [toolId]: { ...(current[toolId] || {}), ...patch },
    }));
  }

  function updateEvidenceType(toolId: string, value: string, run?: WorkflowRun) {
    setFormPatch(toolId, {
      evidenceType: value,
      ...(value === "real-database-acceptance" ? firstDatabaseBindingPatch(run) : {}),
    });
  }
}

function evidenceTypesForItem(item: ToolCatalogProductionQueueItem): string[] {
  const values = item.productionPlan?.acceptedEvidenceTypes?.filter(Boolean) ?? [];
  return values.length ? Array.from(new Set(values)) : [DEFAULT_EVIDENCE_TYPE];
}

function defaultForm(item: ToolCatalogProductionQueueItem): ProductionEvidenceForm {
  return {
    evidenceType: evidenceTypesForItem(item)[0] || DEFAULT_EVIDENCE_TYPE,
    message: "",
    artifactId: "",
    artifactName: "",
    artifactDigest: "",
    logPath: "",
    targetPlatform: DEFAULT_TARGET_PLATFORM,
    policyVersion: DEFAULT_POLICY_VERSION,
    databaseId: "",
    templateId: "",
    role: "",
    packId: "",
    packChecksum: "",
  };
}

function formForItem(
  forms: Record<string, Partial<ProductionEvidenceForm>>,
  item: ToolCatalogProductionQueueItem
): ProductionEvidenceForm {
  return { ...defaultForm(item), ...(forms[item.toolId] || {}) };
}

function missingSubmitField(form: ProductionEvidenceForm, runId: string, runDetailReady: boolean): string {
  if (!runId.trim()) return "runId";
  if (!runDetailReady) return "run detail";
  if (!form.evidenceType.trim()) return "evidenceType";
  if (!form.message.trim()) return "message";
  if (form.evidenceType !== "real-database-acceptance") return "";
  if (!form.databaseId.trim()) return "databaseId";
  if (!form.templateId.trim()) return "templateId";
  if (!form.role.trim()) return "role";
  return "";
}

function buildProductionEvidencePayload({
  activeRun,
  artifact,
  form,
  runId,
}: {
  activeRun?: WorkflowRun;
  artifact?: WorkflowArtifact;
  form: ProductionEvidenceForm;
  runId: string;
}): ToolProductionEvidencePayload {
  const payload: ToolProductionEvidencePayload = {
    runId: runId.trim(),
    evidenceType: form.evidenceType.trim(),
    message: form.message.trim(),
  };
  addString(payload, "artifactName", form.artifactName || artifactEvidenceName(artifact));
  addString(payload, "artifactDigest", form.artifactDigest || artifactDigest(artifact));
  addString(payload, "logPath", form.logPath);
  addString(payload, "targetPlatform", form.targetPlatform);
  addString(payload, "policyVersion", form.policyVersion);
  addString(payload, "databaseId", form.databaseId);
  addString(payload, "templateId", form.templateId);
  addString(payload, "role", form.role);
  addString(payload, "packId", form.packId);
  addString(payload, "packChecksum", form.packChecksum);
  const inputScope = inputScopeFromRun(activeRun);
  if (inputScope) payload.inputScope = inputScope;
  return payload;
}

function addString(payload: ToolProductionEvidencePayload, key: keyof ToolProductionEvidencePayload, value?: string) {
  const normalized = String(value || "").trim();
  if (normalized) {
    (payload as Record<string, unknown>)[key] = normalized;
  }
}

function isCompletedGeneratedToolRun(run: WorkflowRun): boolean {
  const status = String(run.status || "").toLowerCase();
  const pipelineId = String(run.pipelineId || run.runSpec?.pipelineId || "");
  return (status === "completed" || status === "success") && pipelineId === GENERATED_TOOL_RUN_PIPELINE_ID;
}

function runTime(run: WorkflowRun): number {
  const raw = run.finishedAt || run.updatedAt || run.createdAt || run.startedAt || run.submittedAt || "";
  const value = raw ? new Date(raw).getTime() : 0;
  return Number.isFinite(value) ? value : 0;
}

function runLabel(run: WorkflowRun): string {
  const at = run.finishedAt || run.updatedAt || run.createdAt || "";
  const date = at ? new Date(at).toLocaleString("zh-CN") : "unknown time";
  return `${run.runId} · ${date}`;
}

function runDetailSummary(detail: WorkflowRunDetail | null, artifacts: WorkflowArtifact[]): string {
  if (!detail) return "未读取运行详情";
  return `${detail.run.status} · ${artifacts.length} artifacts · ${detail.results?.resultId || detail.run.runId}`;
}

function artifactName(artifact?: WorkflowArtifact): string {
  if (!artifact) return "";
  return artifact.kind || artifact.artifactId;
}

function artifactEvidenceName(artifact?: WorkflowArtifact): string {
  if (!artifact) return "";
  return artifact.artifactId || artifactName(artifact);
}

function artifactLabel(artifact: WorkflowArtifact): string {
  const name = artifactName(artifact);
  const artifactId = artifactEvidenceName(artifact);
  return artifactId && artifactId !== name ? `${name} · ${artifactId}` : name;
}

function artifactDigest(artifact?: WorkflowArtifact): string {
  const sha = String(artifact?.sha256 || "").trim();
  if (!sha) return "";
  return sha.startsWith("sha256:") ? sha : `sha256:${sha}`;
}

function selectedArtifactForForm(artifacts: WorkflowArtifact[], form: ProductionEvidenceForm): WorkflowArtifact | undefined {
  if (form.artifactId.trim()) {
    return artifacts.find((artifact) => artifact.artifactId === form.artifactId.trim());
  }
  const name = form.artifactName.trim();
  if (!name) return artifacts.length === 1 ? artifacts[0] : undefined;
  return artifacts.find(
    (artifact) =>
      artifactEvidenceName(artifact) === name ||
      artifactName(artifact) === name ||
      artifactDigest(artifact) === name,
  );
}

function inputScopeFromRun(run?: WorkflowRun): Record<string, unknown> | undefined {
  if (!run) return undefined;
  const runSpec = run.runSpec || {};
  const inputs = Array.isArray(runSpec.inputs) ? runSpec.inputs : [];
  return {
    pipelineId: runSpec.pipelineId || run.pipelineId || "",
    workflowRevisionId: runSpec.workflowRevisionId || run.workflowRevisionId || "",
    inputs: inputs.map((input) => ({
      filename: input.filename || "",
      role: input.role || "",
      uploadId: input.uploadId || "",
    })),
  };
}

function evidenceScopeSummary(activeRun: WorkflowRun | undefined, artifacts: WorkflowArtifact[]): string {
  if (!activeRun) return "选择 completed generated-tool-run-v1 运行后提交";
  const inputCount = activeRun.runSpec?.inputs?.length ?? 0;
  return `${inputCount} inputs · ${artifacts.length} artifacts · ${activeRun.pipelineId || activeRun.runSpec?.pipelineId || ""}`;
}

function firstDatabaseBindingPatch(run?: WorkflowRun): Partial<ProductionEvidenceForm> {
  const bindings = run?.runSpec?.resourceBindings || {};
  const entries = Object.entries(bindings);
  for (const [role, rawBinding] of entries) {
    if (!rawBinding) continue;
    if (typeof rawBinding === "string") {
      return { role, databaseId: rawBinding };
    }
    if (typeof rawBinding === "object" && !Array.isArray(rawBinding)) {
      const binding = rawBinding as { databaseId?: string; id?: string; templateId?: string };
      return {
        role,
        databaseId: binding.databaseId || binding.id || "",
        templateId: binding.templateId || "",
      };
    }
  }
  return {};
}
