"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Archive, Download, Loader2, Package, RefreshCw } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

import {
  exportWorkflowResultPackage,
  fetchWorkflowResultPackageExports,
  retireWorkflowResultPackage,
  workflowResultPackageDownloadHref,
} from "./workflows-page-api";
import {
  canRetireResultPackage,
  resultPackageActionConfirmation,
  resultPackageBytesState,
  resultPackageLifecycleState,
  type ResultPackageLifecycleAction,
} from "./workflow-result-package-state";
import { workflowErrorMessage } from "./workflows-page-model";
import type { WorkflowResultPackageExport, WorkflowRun } from "./workflows-page-model";

type ExportMode = "full" | "metadata";
type PendingLifecycleAction = {
  action: ResultPackageLifecycleAction;
  item: WorkflowResultPackageExport;
};

export function WorkflowResultPackagePanel({
  resultId,
  run,
  workflowRevisionId,
}: {
  resultId?: string;
  run: WorkflowRun;
  workflowRevisionId?: string;
}) {
  const [exportingMode, setExportingMode] = useState<ExportMode | "">("");
  const [exportError, setExportError] = useState("");
  const [packageExports, setPackageExports] = useState<WorkflowResultPackageExport[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState("");
  const [pendingLifecycleAction, setPendingLifecycleAction] = useState<PendingLifecycleAction | null>(null);
  const [confirmationValue, setConfirmationValue] = useState("");
  const [lifecycleActionError, setLifecycleActionError] = useState("");
  const [lifecycleActionBusyKey, setLifecycleActionBusyKey] = useState("");
  const disabledReason = resultPackageDisabledReason({ resultId, run, workflowRevisionId });
  const canExport = disabledReason.length === 0;

  const loadPackageExports = useCallback(async () => {
    if (!resultId) {
      setPackageExports([]);
      setListError("");
      return;
    }
    setListLoading(true);
    setListError("");
    try {
      setPackageExports(await fetchWorkflowResultPackageExports(resultId));
    } catch (err) {
      setListError(workflowErrorMessage(err, "结果包记录加载失败"));
    } finally {
      setListLoading(false);
    }
  }, [resultId]);

  useEffect(() => {
    void loadPackageExports();
  }, [loadPackageExports]);

  async function handleExport(mode: ExportMode) {
    if (!resultId || !canExport) return;
    setExportingMode(mode);
    setExportError("");
    try {
      const item = await exportWorkflowResultPackage(resultId, mode === "full");
      setPackageExports((current) => mergeResultPackageExport(item, current));
    } catch (err) {
      setExportError(workflowErrorMessage(err, "结果包导出失败"));
    } finally {
      setExportingMode("");
    }
  }

  function openLifecycleAction(action: ResultPackageLifecycleAction, item: WorkflowResultPackageExport) {
    setPendingLifecycleAction({ action, item });
    setConfirmationValue("");
    setLifecycleActionError("");
  }

  function closeLifecycleAction() {
    if (lifecycleActionBusyKey) return;
    setPendingLifecycleAction(null);
    setConfirmationValue("");
    setLifecycleActionError("");
  }

  async function handleLifecycleAction() {
    if (!resultId || !pendingLifecycleAction) return;
    const packageExportId = pendingLifecycleAction.item.packageExportId || "";
    const confirmation = resultPackageActionConfirmation();
    if (!packageExportId || confirmationValue.trim() !== confirmation) return;
    const busyKey = lifecycleActionKey(pendingLifecycleAction.action, packageExportId);
    setLifecycleActionBusyKey(busyKey);
    setLifecycleActionError("");
    try {
      const updated = await retireWorkflowResultPackage(resultId, packageExportId);
      setPackageExports((current) => mergeResultPackageExport(updated, current));
      setPendingLifecycleAction(null);
      setConfirmationValue("");
    } catch (err) {
      setLifecycleActionError(
        workflowErrorMessage(err, "结果包退役失败")
      );
    } finally {
      setLifecycleActionBusyKey("");
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4" data-testid="workflow-result-package-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Package strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
            结果包
          </div>
          <div className="mt-1 truncate font-mono text-[11px] text-slate-400">
            {resultId || "resultId unavailable"}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="h-8 px-2 text-xs"
            disabled={!canExport || Boolean(exportingMode)}
            onClick={() => handleExport("metadata")}
            data-testid="workflow-result-package-export-metadata"
          >
            {exportingMode === "metadata" ? <Loader2 strokeWidth={1.5} className="mr-1 h-3 w-3 animate-spin" /> : null}
            metadata-only
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-8 px-2 text-xs"
            disabled={!canExport || Boolean(exportingMode)}
            onClick={() => handleExport("full")}
            data-testid="workflow-result-package-export-full"
          >
            {exportingMode === "full" ? <Loader2 strokeWidth={1.5} className="mr-1 h-3 w-3 animate-spin" /> : null}
            含产物文件
          </Button>
        </div>
      </div>

      {disabledReason ? (
        <div className="mt-3 rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-700">
          {disabledReason}
        </div>
      ) : null}

      {exportError ? (
        <Alert variant="destructive" className="mt-3">
          <AlertCircle strokeWidth={1.5} className="h-4 w-4" />
          <AlertDescription>{exportError}</AlertDescription>
        </Alert>
      ) : null}

      <div className="mt-3 border-t border-slate-100 pt-3">
        <div className="flex items-center justify-between gap-2">
          <div className="text-xs font-medium text-slate-500">导出记录</div>
          <Button
            variant="outline"
            size="sm"
            className="h-7 px-2 text-xs"
            disabled={!resultId || listLoading}
            onClick={() => void loadPackageExports()}
          >
            <RefreshCw strokeWidth={1.5} className={listLoading ? "h-3 w-3 animate-spin" : "h-3 w-3"} />
            刷新
          </Button>
        </div>
        {listError ? (
          <Alert variant="destructive" className="mt-3">
            <AlertCircle strokeWidth={1.5} className="h-4 w-4" />
            <AlertDescription>{listError}</AlertDescription>
          </Alert>
        ) : null}
        {packageExports.length > 0 ? (
          <div className="mt-2 divide-y divide-slate-100">
            {packageExports.map((item) => (
              <ResultPackageSummary
                key={item.packageExportId || `${item.sha256}-${item.createdAt}`}
                item={item}
                actionBusyKey={lifecycleActionBusyKey}
                onLifecycleAction={openLifecycleAction}
              />
            ))}
          </div>
        ) : (
          <div className="mt-2 text-xs text-slate-400">{listLoading ? "加载中..." : "暂无结果包记录"}</div>
        )}
      </div>
      <ResultPackageLifecycleDialog
        pending={pendingLifecycleAction}
        confirmationValue={confirmationValue}
        error={lifecycleActionError}
        busy={Boolean(lifecycleActionBusyKey)}
        onConfirm={() => void handleLifecycleAction()}
        onConfirmationChange={setConfirmationValue}
        onClose={closeLifecycleAction}
      />
    </div>
  );
}

function ResultPackageSummary({
  actionBusyKey,
  item,
  onLifecycleAction,
}: {
  actionBusyKey: string;
  item: WorkflowResultPackageExport;
  onLifecycleAction: (action: ResultPackageLifecycleAction, item: WorkflowResultPackageExport) => void;
}) {
  const downloadHref = workflowResultPackageDownloadHref(item);
  const lifecycleState = resultPackageLifecycleState(item);
  const bytesState = resultPackageBytesState(item);
  const lifecycleLabel = lifecycleState || "unknown";
  const bytesLabel = bytesState || "unknown";
  const packageExportId = item.packageExportId || "";
  const retireBusy = actionBusyKey === lifecycleActionKey("retire", packageExportId);
  return (
    <div
      className="grid gap-2 py-3 text-xs"
      data-testid="workflow-result-package-export-row"
      data-package-bytes-state={bytesState}
      data-package-download-available={downloadHref ? "true" : "false"}
      data-package-export-id={packageExportId}
      data-package-lifecycle-state={lifecycleState}
      data-package-payload-mode={item.artifactPayloadMode || (item.includeArtifacts ? "full" : "metadata-only")}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className={lifecycleState === "active" ? "font-medium text-emerald-700" : "font-medium text-slate-500"}>
          {lifecycleLabel}
        </span>
        <div className="flex flex-wrap items-center gap-2">
          {downloadHref ? (
            <Button asChild variant="outline" size="sm" className="h-8 px-2 text-xs">
              <a href={downloadHref} download={item.download?.filename || undefined} data-testid="workflow-result-package-download">
                <Download strokeWidth={1.5} className="h-3 w-3" />
                下载结果包
              </a>
            </Button>
          ) : null}
          {canRetireResultPackage(item) ? (
            <Button
              variant="outline"
              size="sm"
              className="h-8 px-2 text-xs"
              disabled={!packageExportId || Boolean(actionBusyKey)}
              onClick={() => onLifecycleAction("retire", item)}
            >
              {retireBusy ? <Loader2 strokeWidth={1.5} className="h-3 w-3 animate-spin" /> : <Archive strokeWidth={1.5} className="h-3 w-3" />}
              退役
            </Button>
          ) : null}
        </div>
      </div>
      <PackageField label="package" value={item.packageExportId} mono />
      <PackageField label="bytes" value={bytesLabel} />
      <PackageField label="payload" value={item.artifactPayloadMode || (item.includeArtifacts ? "full" : "metadata-only")} />
      <PackageField label="size" value={formatPackageBytes(item.sizeBytes)} />
      <PackageField label="sha256" value={item.sha256} mono />
      <PackageField label="manifest" value={item.manifestSha256} mono />
      <PackageField label="evidence" value={item.evidenceId} mono />
      <PackageField label="artifacts" value={formatPackageArtifactCount(item.artifactIds)} />
      <PackageField label="bytes deleted" value={item.packageBytesDeletedAt} mono />
      <PackageField label="created" value={item.createdAt} mono />
    </div>
  );
}

function ResultPackageLifecycleDialog({
  busy,
  confirmationValue,
  error,
  onClose,
  onConfirm,
  onConfirmationChange,
  pending,
}: {
  busy: boolean;
  confirmationValue: string;
  error: string;
  onClose: () => void;
  onConfirm: () => void;
  onConfirmationChange: (value: string) => void;
  pending: PendingLifecycleAction | null;
}) {
  const confirmation = pending ? resultPackageActionConfirmation() : "";
  const canConfirm = Boolean(pending) && confirmationValue.trim() === confirmation && !busy;
  return (
    <Dialog open={Boolean(pending)} onOpenChange={(open) => (!open ? onClose() : null)}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-base">{pending ? lifecycleActionTitle() : "结果包生命周期"}</DialogTitle>
          <DialogDescription className="text-xs">
            {pending ? lifecycleActionDescription() : ""}
          </DialogDescription>
        </DialogHeader>
        {pending ? (
          <div className="grid gap-3 text-xs">
            <div className="grid gap-1">
              <span className="text-slate-400">package</span>
              <span className="break-all font-mono text-[11px] text-slate-700">{pending.item.packageExportId}</span>
            </div>
            <div className="rounded border border-slate-200 bg-slate-50 px-3 py-2">
              <span className="text-slate-500">输入确认码 </span>
              <span className="break-all font-mono text-[11px] text-slate-800">{confirmation}</span>
            </div>
            <Input
              value={confirmationValue}
              disabled={busy}
              placeholder={confirmation}
              onChange={(event) => onConfirmationChange(event.target.value)}
            />
            {error ? (
              <Alert variant="destructive">
                <AlertCircle strokeWidth={1.5} className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" disabled={busy} onClick={onClose}>
                取消
              </Button>
              <Button
                variant="default"
                size="sm"
                disabled={!canConfirm}
                onClick={onConfirm}
              >
                {busy ? <Loader2 strokeWidth={1.5} className="h-3 w-3 animate-spin" /> : lifecycleActionIcon()}
                确认
              </Button>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function PackageField({ label, mono = false, value }: { label: string; mono?: boolean; value?: string }) {
  if (!value) return null;
  return (
    <div className="grid min-w-0 gap-1 sm:grid-cols-[90px_minmax(0,1fr)]">
      <span className="text-slate-400">{label}</span>
      <span className={mono ? "truncate font-mono text-[11px] text-slate-700" : "truncate text-slate-700"}>{value}</span>
    </div>
  );
}

function resultPackageDisabledReason({
  resultId,
  run,
  workflowRevisionId,
}: {
  resultId?: string;
  run: WorkflowRun;
  workflowRevisionId?: string;
}) {
  if (!resultId) return "缺少 resultId";
  if (!isResultPackageExportableRunStatus(run.status)) return "仅 completed/failed 运行可导出";
  if (!workflowRevisionId) return "缺少 WorkflowRevision";
  return "";
}

function isResultPackageExportableRunStatus(status: string | undefined) {
  return status === "completed" || status === "failed";
}

function formatPackageBytes(bytes: number | undefined): string {
  if (!bytes) return "";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.min(sizes.length - 1, Math.floor(Math.log(bytes) / Math.log(k)));
  return `${parseFloat((bytes / k ** i).toFixed(2))} ${sizes[i]}`;
}

function formatPackageArtifactCount(artifactIds: string[] | undefined): string {
  if (!artifactIds?.length) return "";
  return `${artifactIds.length}`;
}

function lifecycleActionKey(action: ResultPackageLifecycleAction, packageExportId: string): string {
  return `${action}:${packageExportId}`;
}

function lifecycleActionTitle(): string {
  return "退役结果包";
}

function lifecycleActionDescription(): string {
  return "退役会保留导出记录和审计证据，并停止该结果包下载。";
}

function lifecycleActionIcon() {
  return <Archive strokeWidth={1.5} className="h-3 w-3" />;
}

function mergeResultPackageExport(
  item: WorkflowResultPackageExport,
  current: WorkflowResultPackageExport[]
): WorkflowResultPackageExport[] {
  const packageExportId = item.packageExportId || "";
  if (!packageExportId) return [item, ...current];
  const existing = current.find((candidate) => candidate.packageExportId === packageExportId);
  const merged = existing ? { ...existing, ...item } : item;
  return [merged, ...current.filter((candidate) => candidate.packageExportId !== packageExportId)];
}
