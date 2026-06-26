"use client";

import { type FormEvent, useState } from "react";
import { Archive, Eye, Loader2, ShieldCheck, Trash2 } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import {
  previewResultPackageByteGc,
  runResultPackageByteGc,
} from "./workflow-artifact-lifecycle-api";
import type {
  WorkflowResultPackageByteGcItem,
  WorkflowResultPackageByteGcPlan,
  WorkflowResultPackageByteGcPreviewRequest,
  WorkflowResultPackageByteGcRunResult,
} from "./workflow-artifact-lifecycle-model";
import { workflowErrorMessage } from "./workflows-page-model";

const RESULT_PACKAGE_BYTE_GC_CONFIRMATION = "run-result-package-byte-gc";
const RESULT_PACKAGE_BYTE_GC_REASON = "web-ui-result-package-byte-gc-preview";

type WorkflowResultPackageByteGcPanelProps = {
  onRunComplete?: () => void;
};

export function WorkflowResultPackageByteGcPanel({
  onRunComplete,
}: WorkflowResultPackageByteGcPanelProps) {
  const [retentionDaysInput, setRetentionDaysInput] = useState("30");
  const [maxDeleteBytesInput, setMaxDeleteBytesInput] = useState("");
  const [scanLimitInput, setScanLimitInput] = useState("1000");
  const [preview, setPreview] = useState<WorkflowResultPackageByteGcPlan | null>(null);
  const [previewRequest, setPreviewRequest] = useState<WorkflowResultPackageByteGcPreviewRequest | null>(null);
  const [runResult, setRunResult] = useState<WorkflowResultPackageByteGcRunResult | null>(null);
  const [confirmationValue, setConfirmationValue] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [runLoading, setRunLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [runError, setRunError] = useState("");

  async function submitPreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPreviewLoading(true);
    setPreviewError("");
    setRunError("");
    try {
      const request: WorkflowResultPackageByteGcPreviewRequest = {
        retentionDays: parseRequiredNonNegativeInteger(retentionDaysInput, 30),
        scanLimit: parseRequiredPositiveInteger(scanLimitInput, 1000, 5000),
        actor: "web-ui",
        reason: RESULT_PACKAGE_BYTE_GC_REASON,
      };
      const maxDeleteBytes = parseOptionalPositiveInteger(maxDeleteBytesInput);
      if (maxDeleteBytes !== undefined) request.maxDeleteBytes = maxDeleteBytes;
      const plan = await previewResultPackageByteGc(request);
      setPreview(plan);
      setPreviewRequest(request);
      setRunResult(null);
      setConfirmationValue("");
    } catch (err) {
      setPreviewError(resultPackageByteGcErrorMessage(err, "生成结果包字节 GC 预览失败"));
    } finally {
      setPreviewLoading(false);
    }
  }

  async function executePreview() {
    if (!preview || !previewRequest || !preview.planFingerprint) return;
    setRunLoading(true);
    setRunError("");
    try {
      const result = await runResultPackageByteGc({
        ...previewRequest,
        confirmation: RESULT_PACKAGE_BYTE_GC_CONFIRMATION,
        planFingerprint: preview.planFingerprint,
      });
      setRunResult(result);
      setPreview(null);
      setPreviewRequest(null);
      setConfirmationValue("");
      onRunComplete?.();
    } catch (err) {
      setRunError(resultPackageByteGcErrorMessage(err, "执行结果包字节 GC 失败"));
    } finally {
      setRunLoading(false);
    }
  }

  function clearSavedPreview() {
    setPreview(null);
    setPreviewRequest(null);
    setRunResult(null);
    setConfirmationValue("");
    setRunError("");
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Archive strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
          <h2 className="text-sm font-semibold text-slate-900">结果包 ZIP 字节 GC</h2>
        </div>
        <span className="text-xs text-slate-400">retired exports only</span>
      </div>

      <form className="grid gap-3 lg:grid-cols-[1fr_1fr_1fr_auto]" onSubmit={submitPreview}>
        <div>
          <Label htmlFor="result-package-byte-gc-retention" className="text-xs text-slate-500">
            保留天数
          </Label>
          <Input
            id="result-package-byte-gc-retention"
            inputMode="numeric"
            value={retentionDaysInput}
            onChange={(event) => {
              setRetentionDaysInput(event.target.value);
              clearSavedPreview();
            }}
          />
        </div>
        <div>
          <Label htmlFor="result-package-byte-gc-max-delete" className="text-xs text-slate-500">
            本批最大字节
          </Label>
          <Input
            id="result-package-byte-gc-max-delete"
            inputMode="numeric"
            placeholder="不限制"
            value={maxDeleteBytesInput}
            onChange={(event) => {
              setMaxDeleteBytesInput(event.target.value);
              clearSavedPreview();
            }}
          />
        </div>
        <div>
          <Label htmlFor="result-package-byte-gc-scan-limit" className="text-xs text-slate-500">
            扫描上限
          </Label>
          <Input
            id="result-package-byte-gc-scan-limit"
            inputMode="numeric"
            value={scanLimitInput}
            onChange={(event) => {
              setScanLimitInput(event.target.value);
              clearSavedPreview();
            }}
          />
        </div>
        <Button type="submit" className="self-end" disabled={previewLoading}>
          {previewLoading ? (
            <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Eye strokeWidth={1.5} className="mr-2 h-4 w-4" />
          )}
          生成预览
        </Button>
      </form>

      {previewError ? (
        <Alert variant="destructive" className="mt-4">
          <AlertDescription>{previewError}</AlertDescription>
        </Alert>
      ) : null}

      <ResultPackageByteGcPreviewSummary preview={preview} previewRequest={previewRequest} />
      <ResultPackageByteGcRunControls
        busy={runLoading}
        confirmationValue={confirmationValue}
        error={runError}
        onConfirmationChange={setConfirmationValue}
        onRun={() => void executePreview()}
        preview={preview}
        previewRequest={previewRequest}
        result={runResult}
      />
    </section>
  );
}

function ResultPackageByteGcPreviewSummary({
  preview,
  previewRequest,
}: {
  preview: WorkflowResultPackageByteGcPlan | null;
  previewRequest: WorkflowResultPackageByteGcPreviewRequest | null;
}) {
  if (!preview) {
    return (
      <div className="mt-4 rounded-lg border border-slate-100 bg-slate-50 px-3 py-4 text-sm text-slate-500">
        暂无结果包字节 GC 预览
      </div>
    );
  }
  const reasonCounts = Object.entries(preview.reasonCounts || {});
  return (
    <div className="mt-4 space-y-4">
      <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-3 text-xs text-slate-600">
        <div className="grid gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium text-slate-700">预览策略</span>
            <span>{formatDateTime(preview.previewedAt)}</span>
          </div>
          <div className="grid gap-2 sm:grid-cols-3">
            <span>保留 {previewRequest?.retentionDays ?? preview.policy?.retentionDays ?? "—"} 天</span>
            <span>扫描 {formatCount(preview.scannedCount)} 项</span>
            <span>本批上限 {formatBytes(previewRequest?.maxDeleteBytes ?? preview.policy?.maxDeleteBytes)}</span>
          </div>
          <div className="text-slate-500">cutoff {formatDateTime(preview.cutoffAt)}</div>
          <div className="break-all font-mono text-[11px] text-slate-500">
            {preview.planFingerprint || "plan fingerprint unavailable"}
          </div>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <ByteGcMetric label="候选 ZIP" value={formatCount(preview.candidateCount)} tone={preview.candidateCount ? "warn" : "default"} />
        <ByteGcMetric label="候选字节" value={formatBytes(preview.deleteBytes)} tone={preview.deleteBytes ? "warn" : "default"} />
        <ByteGcMetric label="受保护 ZIP" value={formatCount(preview.protectedCount)} />
        <ByteGcMetric label="受保护字节" value={formatBytes(preview.protectedBytes)} />
        <ByteGcMetric label="扫描上限" value={formatCount(preview.policy?.scanLimit)} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-slate-100 px-3 py-3">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-700">
            <Archive strokeWidth={1.5} className="h-3.5 w-3.5" />
            候选摘要
          </div>
          <ResultPackageByteGcItemList items={preview.candidates || []} emptyText="暂无可清理结果包 ZIP" />
        </div>
        <div className="rounded-lg border border-slate-100 px-3 py-3">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-700">
            <ShieldCheck strokeWidth={1.5} className="h-3.5 w-3.5" />
            保护摘要
          </div>
          <ResultPackageByteGcItemList items={preview.protected || []} emptyText="暂无受保护结果包 ZIP" />
        </div>
      </div>

      {reasonCounts.length ? (
        <div className="flex flex-wrap gap-2">
          {reasonCounts.map(([reason, count]) => (
            <span
              key={reason}
              className="rounded border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] text-slate-600"
            >
              {reason} {formatCount(count)}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ResultPackageByteGcRunControls({
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
  preview: WorkflowResultPackageByteGcPlan | null;
  previewRequest: WorkflowResultPackageByteGcPreviewRequest | null;
  result: WorkflowResultPackageByteGcRunResult | null;
}) {
  const planFingerprint = preview?.planFingerprint?.trim() || "";
  const hasRunnablePreview = Boolean(
    preview &&
      previewRequest &&
      planFingerprint &&
      (preview.candidateCount || 0) > 0 &&
      (preview.deleteBytes || 0) > 0
  );
  const canRun = hasRunnablePreview && confirmationValue.trim() === RESULT_PACKAGE_BYTE_GC_CONFIRMATION && !busy;
  if (!preview && !result) return null;

  return (
    <div className="mt-4 space-y-3">
      {preview ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-amber-900">
            <Trash2 strokeWidth={1.5} className="h-4 w-4" />
            执行当前结果包 ZIP 预览
          </div>
          <div className="mt-2 rounded border border-amber-200 bg-white/70 px-3 py-2 text-xs text-amber-800">
            输入确认码 <span className="font-mono text-[11px]">{RESULT_PACKAGE_BYTE_GC_CONFIRMATION}</span>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto]">
            <Input
              value={confirmationValue}
              disabled={busy || !hasRunnablePreview}
              placeholder={RESULT_PACKAGE_BYTE_GC_CONFIRMATION}
              onChange={(event) => onConfirmationChange(event.target.value)}
            />
            <Button type="button" variant="destructive" disabled={!canRun} onClick={onRun}>
              {busy ? (
                <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Trash2 strokeWidth={1.5} className="mr-2 h-4 w-4" />
              )}
              执行 ZIP GC
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
      <ResultPackageByteGcRunResultSummary result={result} />
    </div>
  );
}

function ResultPackageByteGcRunResultSummary({
  result,
}: {
  result: WorkflowResultPackageByteGcRunResult | null;
}) {
  if (!result) return null;
  const deleted = result.deleted || [];
  const errors = result.errors || [];
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-semibold text-slate-900">ZIP GC run {result.status || "completed"}</div>
        <span className="font-mono text-[11px] text-slate-400">{formatDateTime(result.executedAt)}</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <ByteGcMetric label="已删 ZIP" value={formatCount(result.deletedCount)} compact />
        <ByteGcMetric label="已删字节" value={formatBytes(result.deletedBytes)} compact />
        <ByteGcMetric label="错误" value={formatCount(result.errorCount)} tone={result.errorCount ? "warn" : "default"} compact />
      </div>
      {result.planFingerprint ? (
        <div className="mt-3 break-all rounded bg-slate-50 px-3 py-2 font-mono text-[11px] text-slate-500">
          {result.planFingerprint}
        </div>
      ) : null}
      {result.evidenceId ? (
        <div className="mt-2 break-all rounded bg-slate-50 px-3 py-2 font-mono text-[11px] text-slate-500">
          evidence {result.evidenceId}
        </div>
      ) : null}
      {deleted.length ? (
        <div className="mt-3">
          <div className="mb-2 text-xs font-medium text-slate-500">删除摘要</div>
          <ResultPackageByteGcItemList items={deleted} emptyText="暂无删除记录" />
        </div>
      ) : null}
      {errors.length ? (
        <div className="mt-3 space-y-2">
          <div className="text-xs font-medium text-slate-500">错误摘要</div>
          {errors.map((item, index) => (
            <div
              key={`${item.itemIndex ?? index}:${item.errorCode || "error"}`}
              className="flex flex-wrap justify-between gap-2 rounded border border-amber-200 bg-amber-50 px-2.5 py-2 text-xs text-amber-800"
            >
              <span>item {formatCount(item.itemIndex ?? index)}</span>
              <span className="font-mono text-[11px]">{item.errorCode || "RESULT_PACKAGE_BYTE_GC_RUN_DELETE_FAILED"}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ResultPackageByteGcItemList({
  items,
  emptyText,
}: {
  items: WorkflowResultPackageByteGcItem[];
  emptyText: string;
}) {
  const visibleItems = items.slice(0, 5);
  if (visibleItems.length === 0) {
    return <div className="text-xs text-slate-400">{emptyText}</div>;
  }
  return (
    <div className="space-y-2">
      {visibleItems.map((item, index) => (
        <div key={`${item.itemIndex ?? index}:${item.reason || "reason"}`} className="rounded border border-slate-100 bg-white px-2.5 py-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-mono text-[11px] text-slate-500">#{(item.itemIndex ?? index) + 1}</span>
            <span className="text-xs font-medium text-slate-700">{formatBytes(item.sizeBytes)}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] text-slate-500">
            <span>{item.reason || "reason: —"}</span>
            <span>{item.lifecycleState || "lifecycle: —"}</span>
            <span>{item.packageBytesState || "bytes: —"}</span>
            <span>{item.artifactPayloadMode || "payload: —"}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] text-slate-500">
            <span>{item.retiredAtPresent ? "retired-at present" : "retired-at missing"}</span>
            <span>{item.checksumVerified ? "checksum verified" : "checksum not verified"}</span>
            {item.packageFileDeleted ? <span>package file deleted</span> : null}
            {item.evidenceId ? <span className="break-all font-mono">evidence {item.evidenceId}</span> : null}
          </div>
        </div>
      ))}
      {items.length > visibleItems.length ? (
        <div className="text-xs text-slate-400">另有 {items.length - visibleItems.length} 项</div>
      ) : null}
    </div>
  );
}

function ByteGcMetric({
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

function parseOptionalNonNegativeInteger(value: string) {
  const normalized = value.trim();
  if (!normalized) return undefined;
  const parsed = Number(normalized);
  if (!Number.isFinite(parsed)) return undefined;
  return Math.max(0, Math.floor(parsed));
}

function parseOptionalPositiveInteger(value: string) {
  const parsed = parseOptionalNonNegativeInteger(value);
  return parsed && parsed > 0 ? parsed : undefined;
}

function parseRequiredNonNegativeInteger(value: string, fallback: number) {
  return parseOptionalNonNegativeInteger(value) ?? fallback;
}

function parseRequiredPositiveInteger(value: string, fallback: number, max: number) {
  const parsed = parseOptionalPositiveInteger(value) ?? fallback;
  return Math.min(Math.max(1, parsed), max);
}

function resultPackageByteGcErrorMessage(err: unknown, fallback: string) {
  const message = workflowErrorMessage(err, fallback);
  const status = typeof err === "object" && err && "status" in err ? Number((err as { status?: unknown }).status) : 0;
  if (status === 404 || /^not found$/i.test(message)) {
    return "当前远程 runner 未暴露结果包字节 GC API，请部署包含 result-package byte GC endpoints 的 runner 后重试。";
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
