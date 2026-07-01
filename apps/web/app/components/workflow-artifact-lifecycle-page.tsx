"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Archive,
  ArrowLeft,
  Eye,
  Gauge,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import {
  fetchArtifactLifecycleControllerTicks,
  fetchArtifactLifecycleUsage,
  previewArtifactGc,
  runArtifactLifecycleControllerOnce,
  runArtifactGc,
} from "./workflow-artifact-lifecycle-api";
import { WorkflowArtifactCacheController } from "./workflow-artifact-cache-controller";
import { WorkflowArtifactLifecycleControllerPanel } from "./workflow-artifact-lifecycle-controller-panel";
import { WorkflowResultPackageByteGcPanel } from "./workflow-result-package-byte-gc-panel";
import {
  artifactLifecyclePolicyFingerprint,
  DEFAULT_ELIGIBLE_RUN_STATUSES,
  DEFAULT_GC_POLICY_ID,
  DEFAULT_GC_POLICY_VERSION,
  DEFAULT_GC_REASON,
  DEFAULT_GC_RETENTION_DAYS,
  normalizeArtifactGcReason,
  parseOptionalNonNegativeInteger,
  parseOptionalPositiveInteger,
  parseRequiredNonNegativeInteger,
  type ArtifactGcPolicyInput,
} from "./workflow-artifact-lifecycle-policy";
import type {
  WorkflowArtifactGcPlan,
  WorkflowArtifactGcPlanItem,
  WorkflowArtifactGcPreviewRequest,
  WorkflowArtifactGcRunResult,
  WorkflowArtifactLifecycleControllerTick,
  WorkflowArtifactLifecycleUsage,
} from "./workflow-artifact-lifecycle-model";
import { WorkflowPageHeader } from "./workflow-page-header";
import { workflowErrorMessage } from "./workflows-page-model";

const GC_RUN_CONFIRMATION = "delete-artifact-payloads";

export function WorkflowArtifactLifecyclePage() {
  const [usage, setUsage] = useState<WorkflowArtifactLifecycleUsage | null>(null);
  const [ticks, setTicks] = useState<WorkflowArtifactLifecycleControllerTick[]>([]);
  const [cacheRefreshVersion, setCacheRefreshVersion] = useState(0);
  const [preview, setPreview] = useState<WorkflowArtifactGcPlan | null>(null);
  const [previewRequest, setPreviewRequest] = useState<WorkflowArtifactGcPreviewRequest | null>(null);
  const [runResult, setRunResult] = useState<WorkflowArtifactGcRunResult | null>(null);
  const [retentionDaysInput, setRetentionDaysInput] = useState(DEFAULT_GC_RETENTION_DAYS);
  const [quotaBytesInput, setQuotaBytesInput] = useState("");
  const [maxDeleteBytesInput, setMaxDeleteBytesInput] = useState("");
  const [gcReasonInput, setGcReasonInput] = useState(DEFAULT_GC_REASON);
  const [runConfirmation, setRunConfirmation] = useState("");
  const [loading, setLoading] = useState(true);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [controllerPreviewTickId, setControllerPreviewTickId] = useState("");
  const [controllerRunning, setControllerRunning] = useState(false);
  const [controllerNotice, setControllerNotice] = useState("");
  const [controllerError, setControllerError] = useState("");
  const [runLoading, setRunLoading] = useState(false);
  const [error, setError] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [runError, setRunError] = useState("");

  const load = useCallback(async (forceRefresh = false) => {
    setLoading(true);
    setError("");
    try {
      const quotaBytes = parseOptionalNonNegativeInteger(quotaBytesInput, "配额字节");
      const [nextUsage, nextTicks] = await Promise.all([
        fetchArtifactLifecycleUsage({ forceRefresh, quotaBytes }),
        fetchArtifactLifecycleControllerTicks({ forceRefresh, limit: 25 }),
      ]);
      setUsage(nextUsage);
      setTicks(nextTicks.items || []);
    } catch (err) {
      setError(artifactLifecycleErrorMessage(err, "读取产物生命周期失败"));
    } finally {
      setLoading(false);
    }
  }, [quotaBytesInput]);

  useEffect(() => {
    void load();
  }, [load]);

  async function submitPreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPreviewLoading(true);
    setPreviewError("");
    setRunError("");
    try {
      const request = await buildManualArtifactGcPreviewRequest();
      const plan = await previewArtifactGc(request);
      setPreview(plan);
      setPreviewRequest(request);
      setRunResult(null);
      setRunConfirmation("");
    } catch (err) {
      setPreviewError(artifactLifecycleErrorMessage(err, "生成 GC 预览失败"));
    } finally {
      setPreviewLoading(false);
    }
  }

  async function previewControllerTickPolicy(tick: WorkflowArtifactLifecycleControllerTick) {
    const request = previewRequestFromControllerTick(tick);
    if (!request) return;
    setPreviewLoading(true);
    setControllerPreviewTickId(tick.tickId || tick.evidenceId || "");
    setControllerNotice("");
    setControllerError("");
    setPreviewError("");
    setRunError("");
    setPreview(null);
    setPreviewRequest(null);
    setRunResult(null);
    setRunConfirmation("");
    try {
      const plan = await previewArtifactGc(request);
      setPreview(plan);
      setPreviewRequest(request);
    } catch (err) {
      setPreviewError(artifactLifecycleErrorMessage(err, "生成 GC 预览失败"));
    } finally {
      setPreviewLoading(false);
      setControllerPreviewTickId("");
    }
  }

  async function runControllerOnce() {
    if (controllerRunning) return;
    setControllerRunning(true);
    setControllerNotice("");
    setControllerError("");
    try {
      const policy = readManualArtifactGcPolicyInput();
      const result = await runArtifactLifecycleControllerOnce({
        actor: "web-ui",
        retentionDays: policy.retentionDays,
        eligibleRunStatuses: policy.eligibleRunStatuses,
        quotaBytes: policy.quotaBytes ?? undefined,
        maxDeleteBytesPerTick: policy.maxDeleteBytesPerTick ?? undefined,
        reason: policy.reason,
      });
      setControllerNotice(
        result.tickId
          ? `已生成 controller tick ${result.tickId}`
          : "已生成 controller tick"
      );
      setCacheRefreshVersion((version) => version + 1);
      await load(true);
    } catch (err) {
      setControllerError(artifactLifecycleErrorMessage(err, "运行 artifact lifecycle controller 失败"));
    } finally {
      setControllerRunning(false);
    }
  }

  async function executePreviewGc() {
    if (!preview || !previewRequest || !preview.planFingerprint) return;
    setRunLoading(true);
    setRunError("");
    try {
      const result = await runArtifactGc({
        ...previewRequest,
        confirmation: GC_RUN_CONFIRMATION,
        planFingerprint: preview.planFingerprint,
      });
      setRunResult(result);
      setPreview(null);
      setPreviewRequest(null);
      setRunConfirmation("");
      setCacheRefreshVersion((version) => version + 1);
      await load(true);
    } catch (err) {
      setRunError(artifactLifecycleErrorMessage(err, "执行 GC 失败"));
    } finally {
      setRunLoading(false);
    }
  }

  function clearSavedPreview() {
    setPreview(null);
    setPreviewRequest(null);
    setRunResult(null);
    setRunConfirmation("");
    setRunError("");
  }

  function refresh() {
    setCacheRefreshVersion((version) => version + 1);
    void load(true);
  }

  async function reloadAfterCachePolicyChange() {
    clearSavedPreview();
    await load(true);
  }

  function readManualArtifactGcPolicyInput(): ArtifactGcPolicyInput {
    const retentionDays = parseRequiredNonNegativeInteger(retentionDaysInput, "保留天数");
    const maxDeleteBytesPerTick = parseOptionalPositiveInteger(maxDeleteBytesInput, "本批最大字节");
    const quotaBytes = parseOptionalNonNegativeInteger(quotaBytesInput, "配额字节");
    const reason = normalizeArtifactGcReason(gcReasonInput);
    return {
      retentionDays,
      eligibleRunStatuses: DEFAULT_ELIGIBLE_RUN_STATUSES,
      quotaBytes: quotaBytes ?? null,
      maxDeleteBytesPerTick: maxDeleteBytesPerTick ?? null,
      reason,
    };
  }

  async function buildManualArtifactGcPreviewRequest(): Promise<WorkflowArtifactGcPreviewRequest> {
    const policy = readManualArtifactGcPolicyInput();
    const policyFingerprint = await artifactLifecyclePolicyFingerprint(policy);
    const request: WorkflowArtifactGcPreviewRequest = {
      actor: "web-ui",
      policyId: DEFAULT_GC_POLICY_ID,
      policyVersion: DEFAULT_GC_POLICY_VERSION,
      policyFingerprint,
      persisted: false,
      retentionDays: policy.retentionDays,
      eligibleRunStatuses: policy.eligibleRunStatuses,
      quotaBytes: policy.quotaBytes,
      maxDeleteBytesPerTick: policy.maxDeleteBytesPerTick,
      reason: policy.reason,
    };
    if (policy.maxDeleteBytesPerTick !== null && policy.maxDeleteBytesPerTick !== undefined) {
      request.maxDeleteBytes = policy.maxDeleteBytesPerTick;
    }
    return request;
  }

  return (
    <div className="relative flex-1 h-full w-full overflow-y-auto bg-white px-8 py-10 text-slate-800">
      <div className="mx-auto max-w-6xl space-y-6">
        <WorkflowPageHeader
          title="产物生命周期"
          leading={
            <Button asChild variant="outline" className="h-9 bg-white px-3 text-slate-600">
              <Link href="/workflows/results">
                <ArrowLeft strokeWidth={1.5} className="mr-2 h-4 w-4" />
                返回运行记录
              </Link>
            </Button>
          }
          actions={
            <Button
              type="button"
              variant="outline"
              className="h-9 bg-white px-3 text-slate-600"
              disabled={loading}
              onClick={refresh}
            >
              <RefreshCw strokeWidth={1.5} className={loading ? "mr-2 h-4 w-4 animate-spin" : "mr-2 h-4 w-4"} />
              刷新
            </Button>
          }
        />

        {error ? (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        {loading && !usage ? (
          <div className="flex h-48 items-center justify-center text-sm text-slate-400">
            <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
            正在读取产物生命周期
          </div>
        ) : (
          <>
            <section className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
              <div className="rounded-lg border border-slate-200 bg-white p-5">
                <div className="mb-4 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Gauge strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
                    <h2 className="text-sm font-semibold text-slate-900">存储用量</h2>
                  </div>
                  <span className="text-xs text-slate-400">{formatDateTime(usage?.checkedAt)}</span>
                </div>
                <UsageOverview usage={usage} />
                <div className="mt-5 grid gap-3 sm:grid-cols-[1fr_auto]">
                  <div>
                    <Label htmlFor="artifact-lifecycle-quota" className="text-xs text-slate-500">
                      配额字节
                    </Label>
                    <Input
                      id="artifact-lifecycle-quota"
                      inputMode="numeric"
                      placeholder="可选"
                      value={quotaBytesInput}
                      onChange={(event) => setQuotaBytesInput(event.target.value)}
                    />
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    className="self-end bg-white text-slate-600"
                    onClick={() => void load(true)}
                  >
                    应用配额
                  </Button>
                </div>
                <BackendUsage usage={usage} />
              </div>

              <form className="rounded-lg border border-slate-200 bg-white p-5" onSubmit={submitPreview}>
                <div className="mb-4 flex items-center gap-2">
                  <Eye strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
                  <h2 className="text-sm font-semibold text-slate-900">GC 预览</h2>
                </div>
                <div className="grid gap-3">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <Label htmlFor="artifact-gc-retention" className="text-xs text-slate-500">
                        保留天数
                      </Label>
                      <Input
                        id="artifact-gc-retention"
                        inputMode="numeric"
                        value={retentionDaysInput}
                        onChange={(event) => setRetentionDaysInput(event.target.value)}
                      />
                    </div>
                    <div>
                      <Label htmlFor="artifact-gc-max-delete" className="text-xs text-slate-500">
                        本批最大字节
                      </Label>
                      <Input
                        id="artifact-gc-max-delete"
                        inputMode="numeric"
                        placeholder="可选"
                        value={maxDeleteBytesInput}
                        onChange={(event) => setMaxDeleteBytesInput(event.target.value)}
                      />
                    </div>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <Label htmlFor="artifact-gc-quota" className="text-xs text-slate-500">
                        配额字节
                      </Label>
                      <Input
                        id="artifact-gc-quota"
                        inputMode="numeric"
                        placeholder="可选"
                        value={quotaBytesInput}
                        onChange={(event) => setQuotaBytesInput(event.target.value)}
                      />
                    </div>
                    <div>
                      <Label htmlFor="artifact-gc-reason" className="text-xs text-slate-500">
                        原因
                      </Label>
                      <Input
                        id="artifact-gc-reason"
                        value={gcReasonInput}
                        onChange={(event) => setGcReasonInput(event.target.value)}
                      />
                    </div>
                  </div>
                  <Button type="submit" className="w-full" disabled={previewLoading}>
                    {previewLoading ? <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" /> : <Eye strokeWidth={1.5} className="mr-2 h-4 w-4" />}
                    生成预览
                  </Button>
                </div>
                {previewError ? (
                  <Alert variant="destructive" className="mt-4">
                    <AlertDescription>{previewError}</AlertDescription>
                  </Alert>
                ) : null}
                <GcPreviewSummary preview={preview} previewRequest={previewRequest} />
                <GcRunPanel
                  busy={runLoading}
                  confirmationValue={runConfirmation}
                  error={runError}
                  preview={preview}
                  previewRequest={previewRequest}
                  result={runResult}
                  onConfirmationChange={setRunConfirmation}
                  onRun={() => void executePreviewGc()}
                />
              </form>
            </section>

            <WorkflowArtifactLifecycleControllerPanel
              busyTickId={controllerPreviewTickId}
              error={controllerError}
              notice={controllerNotice}
              onPreviewPolicy={(tick) => void previewControllerTickPolicy(tick)}
              onRunControllerOnce={() => void runControllerOnce()}
              runningController={controllerRunning}
              ticks={ticks}
            />

            <WorkflowResultPackageByteGcPanel onRunComplete={refresh} />

            <WorkflowArtifactCacheController
              onPolicyChanged={reloadAfterCachePolicyChange}
              refreshVersion={cacheRefreshVersion}
            />
          </>
        )}
      </div>
    </div>
  );
}

function UsageOverview({ usage }: { usage: WorkflowArtifactLifecycleUsage | null }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Metric label="活动字节" value={formatBytes(usage?.activeBytes)} />
      <Metric label="活动对象" value={formatCount(usage?.activeStorageObjectCount)} />
      <Metric label="产物记录" value={formatCount(usage?.artifactCount)} />
      <Metric label="Ledger-only" value={formatBytes(usage?.ledgerOnlyActiveBytes)} />
      <Metric label="已删除字节" value={formatBytes(usage?.deletedBytes)} muted />
      <Metric label="活动产物" value={formatCount(usage?.activeArtifactCount)} muted />
      <Metric label="已删产物" value={formatCount(usage?.deletedArtifactCount)} muted />
      <Metric
        label="配额余量"
        value={usage?.quota ? formatBytes(usage.quota.remainingBytes) : "—"}
        tone={usage?.quota?.overageBytes ? "warn" : "default"}
      />
    </div>
  );
}

function BackendUsage({ usage }: { usage: WorkflowArtifactLifecycleUsage | null }) {
  const entries = Object.entries(usage?.byBackend || {});
  if (entries.length === 0) {
    return <div className="mt-4 text-xs text-slate-400">暂无 backend 用量</div>;
  }
  return (
    <div className="mt-4 overflow-hidden rounded-lg border border-slate-100">
      <table className="w-full text-left text-xs">
        <thead className="bg-slate-50 text-slate-500">
          <tr>
            <th className="px-3 py-2 font-medium">Backend</th>
            <th className="px-3 py-2 font-medium">对象</th>
            <th className="px-3 py-2 font-medium text-right">字节</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {entries.map(([backend, item]) => (
            <tr key={backend}>
              <td className="px-3 py-2 font-mono text-slate-700">{backend}</td>
              <td className="px-3 py-2 text-slate-600">{formatCount(item.storageObjectCount)}</td>
              <td className="px-3 py-2 text-right text-slate-600">{formatBytes(item.bytes)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GcPreviewSummary({
  preview,
  previewRequest,
}: {
  preview: WorkflowArtifactGcPlan | null;
  previewRequest: WorkflowArtifactGcPreviewRequest | null;
}) {
  if (!preview) {
    return (
      <div className="mt-4 rounded-lg border border-slate-100 bg-slate-50 px-3 py-4 text-sm text-slate-500">
        暂无预览计划
      </div>
    );
  }
  const candidates = preview.candidates || [];
  const protectedItems = preview.protected || [];
  return (
    <div className="mt-4 space-y-4">
      <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-3 text-xs text-slate-600">
        <div className="grid gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium text-slate-700">预览策略</span>
            <span className="font-mono text-[11px] text-slate-500">{preview.planId || "—"}</span>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <span>保留 {previewRequest?.retentionDays ?? preview.policy?.retentionDays ?? "—"} 天</span>
            <span>本批上限 {formatBytes(previewRequest?.maxDeleteBytes ?? previewRequest?.maxDeleteBytesPerTick ?? preview.policy?.maxDeleteBytes)}</span>
            <span>配额 {formatBytes(previewRequest?.quotaBytes ?? preview.policy?.quotaBytes)}</span>
            <span>超额 {formatBytes(preview.quotaOverageBytes)}</span>
          </div>
          <div className="break-all font-mono text-[11px] text-slate-500">{preview.planFingerprint || "plan fingerprint unavailable"}</div>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Metric label="候选对象" value={formatCount(preview.candidateCount)} tone={preview.candidateCount ? "warn" : "default"} />
        <Metric label="候选字节" value={formatBytes(preview.deleteBytes)} tone={preview.deleteBytes ? "warn" : "default"} />
        <Metric label="受保护对象" value={formatCount(preview.protectedCount)} />
        <Metric label="受保护字节" value={formatBytes(preview.protectedBytes)} />
      </div>
      <div className="rounded-lg border border-slate-100 px-3 py-3">
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-700">
          <Archive strokeWidth={1.5} className="h-3.5 w-3.5" />
          候选摘要
        </div>
        <PlanItemList items={candidates} emptyText="暂无可清理候选" />
      </div>
      <div className="rounded-lg border border-slate-100 px-3 py-3">
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-700">
          <ShieldCheck strokeWidth={1.5} className="h-3.5 w-3.5" />
          Retention holds
        </div>
        <PlanItemList items={protectedItems} emptyText="暂无受保护对象" protectedItems />
      </div>
    </div>
  );
}

function GcRunPanel({
  busy,
  confirmationValue,
  error,
  onConfirmationChange,
  onRun,
  preview,
  previewRequest,
  result,
}: {
  busy: boolean;
  confirmationValue: string;
  error: string;
  onConfirmationChange: (value: string) => void;
  onRun: () => void;
  preview: WorkflowArtifactGcPlan | null;
  previewRequest: WorkflowArtifactGcPreviewRequest | null;
  result: WorkflowArtifactGcRunResult | null;
}) {
  const planFingerprint = preview?.planFingerprint?.trim() || "";
  const hasRunnablePreview = Boolean(
    preview &&
      previewRequest &&
      planFingerprint &&
      (preview.candidateCount || 0) > 0 &&
      (preview.deleteBytes || 0) > 0
  );
  const canRun = hasRunnablePreview && confirmationValue.trim() === GC_RUN_CONFIRMATION && !busy;
  if (!preview && !result) return null;
  return (
    <div className="mt-4 space-y-3">
      {preview ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-amber-900">
            <Trash2 strokeWidth={1.5} className="h-4 w-4" />
            执行当前预览
          </div>
          <div className="mt-2 rounded border border-amber-200 bg-white/70 px-3 py-2 text-xs text-amber-800">
            输入确认码 <span className="font-mono text-[11px]">{GC_RUN_CONFIRMATION}</span>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto]">
            <Input
              value={confirmationValue}
              disabled={busy || !hasRunnablePreview}
              placeholder={GC_RUN_CONFIRMATION}
              onChange={(event) => onConfirmationChange(event.target.value)}
            />
            <Button
              type="button"
              variant="destructive"
              disabled={!canRun}
              onClick={onRun}
            >
              {busy ? <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 strokeWidth={1.5} className="mr-2 h-4 w-4" />}
              执行 GC
            </Button>
          </div>
          {!hasRunnablePreview ? (
            <div className="mt-2 text-xs text-amber-700">当前预览没有可删除候选，或缺少 plan fingerprint。</div>
          ) : null}
        </div>
      ) : null}
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      <GcRunResultSummary result={result} />
    </div>
  );
}

function GcRunResultSummary({ result }: { result: WorkflowArtifactGcRunResult | null }) {
  if (!result) return null;
  const deleted = result.deleted || [];
  const errors = result.errors || [];
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-semibold text-slate-900">GC run {result.status || "completed"}</div>
        <span className="font-mono text-[11px] text-slate-400">{result.executedAt || "—"}</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Metric label="已删对象" value={formatCount(result.deletedCount)} compact />
        <Metric label="已删字节" value={formatBytes(result.deletedBytes)} compact />
        <Metric label="错误" value={formatCount(result.errorCount)} tone={result.errorCount ? "warn" : "default"} compact />
      </div>
      {result.evidenceId ? (
        <div className="mt-3 break-all rounded bg-slate-50 px-3 py-2 font-mono text-[11px] text-slate-500">
          evidence {result.evidenceId}
        </div>
      ) : null}
      {deleted.length ? (
        <div className="mt-3">
          <div className="mb-2 text-xs font-medium text-slate-500">删除摘要</div>
          <PlanItemList items={deleted} emptyText="暂无删除记录" />
        </div>
      ) : null}
      {errors.length ? (
        <div className="mt-3 space-y-2">
          <div className="text-xs font-medium text-slate-500">错误摘要</div>
          {errors.map((item, index) => (
            <div key={`${item.storageBackend || "backend"}:${item.errorCode || "error"}:${index}`} className="flex flex-wrap justify-between gap-2 rounded border border-amber-200 bg-amber-50 px-2.5 py-2 text-xs text-amber-800">
              <span>{item.storageBackend || "backend"}</span>
              <span className="font-mono text-[11px]">{item.errorCode || "ARTIFACT_GC_DELETE_FAILED"}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function PlanItemList({
  items,
  emptyText,
  protectedItems = false,
}: {
  items: WorkflowArtifactGcPlanItem[];
  emptyText: string;
  protectedItems?: boolean;
}) {
  const visibleItems = items.slice(0, 5);
  if (visibleItems.length === 0) {
    return <div className="text-xs text-slate-400">{emptyText}</div>;
  }
  return (
    <div className="space-y-2">
      {visibleItems.map((item, index) => (
        <div key={`${item.storageBackend || "backend"}:${item.sizeBytes || 0}:${index}`} className="rounded border border-slate-100 bg-white px-2.5 py-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-mono text-[11px] text-slate-500">#{index + 1}</span>
            <span className="text-xs font-medium text-slate-700">{formatBytes(item.sizeBytes)}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] text-slate-500">
            <span>{item.storageBackend || "backend: —"}</span>
            {item.reason ? <span>{item.reason}</span> : null}
            <span>artifacts {formatCount(item.artifactCount)}</span>
            <span>runs {formatCount(item.runCount)}</span>
            <span>materializations {formatCount(item.materializationCount)}</span>
          </div>
          {protectedItems && item.reasons?.length ? (
            <div className="mt-1 flex flex-wrap gap-1">
              {item.reasons.slice(0, 4).map((reason) => (
                <span key={reason} className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-600">
                  {reason}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ))}
      {items.length > visibleItems.length ? (
        <div className="text-xs text-slate-400">另有 {items.length - visibleItems.length} 项</div>
      ) : null}
    </div>
  );
}

function controllerTickCanPreviewPolicy(tick: WorkflowArtifactLifecycleControllerTick) {
  const preview = tick.gcPreview;
  return (
    tick.policyDecision?.decision === "preview_ready" &&
    Boolean(preview?.planId.trim()) &&
    Boolean(preview?.planFingerprint.trim()) &&
    (preview?.candidateCount || 0) > 0 &&
    (preview?.deleteBytes || 0) > 0
  );
}

function previewRequestFromControllerTick(
  tick: WorkflowArtifactLifecycleControllerTick
): WorkflowArtifactGcPreviewRequest | null {
  if (!controllerTickCanPreviewPolicy(tick)) return null;
  const policy = tick.policy;
  if (
    !policy?.policyFingerprint?.trim() ||
    policy.retentionDays === undefined ||
    !policy.eligibleRunStatuses?.length ||
    !policy.reason?.trim()
  ) {
    return null;
  }
  const request: WorkflowArtifactGcPreviewRequest = {
    actor: "web-ui",
    policyId: policy.policyId || DEFAULT_GC_POLICY_ID,
    policyVersion: policy.policyVersion ?? DEFAULT_GC_POLICY_VERSION,
    policyFingerprint: policy.policyFingerprint,
    persisted: Boolean(policy.persisted),
    retentionDays: policy.retentionDays,
    eligibleRunStatuses: policy.eligibleRunStatuses,
    quotaBytes: policy.quotaBytes ?? null,
    maxDeleteBytesPerTick: policy.maxDeleteBytesPerTick ?? null,
    reason: policy.reason,
  };
  if (policy.maxDeleteBytesPerTick !== null && policy.maxDeleteBytesPerTick !== undefined) {
    request.maxDeleteBytes = policy.maxDeleteBytesPerTick;
  }
  return request;
}

function Metric({
  label,
  value,
  muted = false,
  tone = "default",
  compact = false,
}: {
  label: string;
  value: string;
  muted?: boolean;
  tone?: "default" | "warn";
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2",
        muted ? "border-slate-100 bg-slate-50" : "border-slate-200 bg-white",
        tone === "warn" ? "border-amber-200 bg-amber-50" : "",
        compact ? "px-2 py-1.5" : ""
      )}
    >
      <div className="text-[11px] font-medium text-slate-500">{label}</div>
      <div className={cn("mt-1 font-semibold text-slate-900", compact ? "text-xs" : "text-sm")}>{value}</div>
    </div>
  );
}

function artifactLifecycleErrorMessage(err: unknown, fallback: string) {
  const message = workflowErrorMessage(err, fallback);
  const status = typeof err === "object" && err && "status" in err ? Number((err as { status?: unknown }).status) : 0;
  if (status === 404 || /^not found$/i.test(message)) {
    return "当前远程 runner 未暴露产物生命周期 API，请部署包含 artifact lifecycle endpoints 的 runner 后重试。";
  }
  return message;
}

function formatCount(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatBytes(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let current = Math.max(0, value);
  let unitIndex = 0;
  while (current >= 1024 && unitIndex < units.length - 1) {
    current /= 1024;
    unitIndex += 1;
  }
  const digits = current >= 10 || unitIndex === 0 ? 0 : 1;
  return `${current.toFixed(digits)} ${units[unitIndex]}`;
}

function formatDateTime(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN");
}
