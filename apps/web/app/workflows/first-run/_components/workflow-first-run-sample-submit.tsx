"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Play, UploadCloud, XCircle } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { formatBytes } from "../_domain/first-run-display";
import { fetchWorkflowSampleDataStatus, type WorkflowSampleDataStatus } from "../_api/workflow-sample-data-api";
import type { FirstRunStatusEvidence } from "../_domain/first-run-types";
import type { WorkflowCatalogItem, WorkflowUpload } from "@/app/components/workflows-page-model";

export const FIRST_RUN_EXPECTED_SAMPLE_ROLES = ["metadata", "barcodes", "sequences"] as const;

export function SampleAndSubmitPanel({
  canSubmit,
  loading,
  onPrepareSample,
  onSubmit,
  pipelineReady,
  sampleCacheEvidence,
  sampleLoading,
  sampleUploads,
  submitError,
  submitting,
  workflow,
  workflowLoading,
}: {
  canSubmit: boolean;
  loading: boolean;
  onPrepareSample: () => void;
  onSubmit: () => void;
  pipelineReady: boolean;
  sampleCacheEvidence?: FirstRunStatusEvidence["sampleCache"];
  sampleLoading: boolean;
  sampleUploads: WorkflowUpload[];
  submitError: string;
  submitting: boolean;
  workflow: WorkflowCatalogItem | null;
  workflowLoading: boolean;
}) {
  const localReady = sampleUploadsReady(sampleUploads);
  const cacheReady = sampleCacheEvidence?.status === "ready";
  const ready = localReady || cacheReady;
  const roleAudit = sampleUploadRoleAudit(sampleUploads);
  const roleBlockers = sampleUploads.length > 0 && !localReady ? sampleUploadRoleBlockers(roleAudit) : [];
  const selection = firstRunWorkflowSelection(workflow, workflowLoading);
  const sampleStatus = useWorkflowSampleDataStatus({
    enabled: pipelineReady && Boolean(workflow?.id) && !sampleLoading,
    pipelineId: workflow?.id || "",
    refreshKey: sampleUploads.map((upload) => `${upload.role || ""}:${upload.sha256 || ""}`).join("|"),
  });
  return (
    <section id="sample-data" className="scroll-mt-24 rounded-lg border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <UploadCloud strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
            选择 Moving Pictures 16S 示例并准备数据
          </div>
          <div className="mt-1 text-xs leading-5 text-slate-500" data-testid="first-run-moving-pictures-pipeline-id">
            {workflow?.id || "moving-pictures-16s-rulegraph-v1"}
          </div>
        </div>
        <span className={cn("rounded-full border px-2 py-1 text-[11px]", pipelineReady ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-red-200 bg-red-50 text-red-700")}>
          {pipelineReady ? "WorkflowReady" : "未就绪"}
        </span>
      </div>

      <div
        className={cn("mt-4 rounded-md border px-3 py-2", selection.tone === "success" ? "border-emerald-200 bg-emerald-50" : selection.tone === "danger" ? "border-red-200 bg-red-50" : "border-amber-200 bg-amber-50")}
        data-testid="first-run-sample-selection"
        data-selection-state={selection.state}
      >
        <div className="flex min-w-0 items-center gap-2 text-xs font-semibold">
          {selection.tone === "success" ? (
            <CheckCircle2 strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
          ) : (
            <XCircle strokeWidth={1.5} className={cn("h-3.5 w-3.5 shrink-0", selection.tone === "danger" ? "text-red-600" : "text-amber-600")} />
          )}
          <span className={cn("truncate", selection.tone === "success" ? "text-emerald-950" : selection.tone === "danger" ? "text-red-950" : "text-amber-950")}>
            {selection.label}
          </span>
        </div>
        <div className={cn("mt-1 text-xs leading-5", selection.tone === "success" ? "text-emerald-800" : selection.tone === "danger" ? "text-red-800" : "text-amber-800")}>
          {selection.detail}
        </div>
      </div>

      <SampleDataStatusPanel
        error={sampleStatus.error}
        loading={sampleStatus.loading}
        ready={ready}
        sampleCacheEvidence={sampleCacheEvidence}
        status={sampleStatus.status}
      />

      {roleBlockers.length > 0 ? (
        <div
          className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700"
          data-testid="first-run-sample-role-audit"
        >
          <div className="font-semibold">样本输入角色不可信</div>
          <div className="mt-1">{roleBlockers.join(" / ")}</div>
        </div>
      ) : null}

      {workflow?.description && pipelineReady ? (
        <p className="mt-3 text-xs leading-5 text-slate-600">{workflow.description}</p>
      ) : null}

      <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
        <div className="grid gap-2">
          {FIRST_RUN_EXPECTED_SAMPLE_ROLES.map((role) => {
            const upload = sampleUploads.find((item) => item.role === role);
            const verified = upload ? sampleIntegrityPassed(upload) : false;
            return (
              <div key={role} className="flex min-w-0 items-center justify-between gap-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
                <div className="min-w-0">
                  <div className="font-medium text-slate-800">{sampleRoleLabel(role)}</div>
                  <div className="mt-0.5 truncate font-mono text-[11px] text-slate-500">{upload?.filename || sampleRoleFilename(role)}</div>
                </div>
                {upload ? (
                  <div className="shrink-0 text-right">
                    <div className={verified ? "text-emerald-700" : "text-red-700"}>
                      {verified ? "checksum verified" : "checksum required"}
                    </div>
                    <div className="mt-0.5 font-mono text-[10px] text-slate-400">{samplePrepProofLabel(upload)}</div>
                    <div className="mt-0.5 font-mono text-[10px] text-slate-400">{sampleIntegrityLabel(upload)}</div>
                  </div>
                ) : cacheReady ? (
                  <span className="shrink-0 text-emerald-700">cache verified</span>
                ) : (
                  <span className="shrink-0 text-slate-400">待准备</span>
                )}
              </div>
            );
          })}
        </div>
        <div className="space-y-2">
          <Button
            className="h-10 w-full bg-slate-950 text-white hover:bg-slate-800"
            disabled={sampleLoading || loading || !pipelineReady}
            onClick={onPrepareSample}
            data-testid="first-run-prepare-sample-data"
          >
            {sampleLoading ? <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" /> : <UploadCloud strokeWidth={1.5} className="mr-2 h-4 w-4" />}
            准备示例数据
          </Button>
          <Button
            variant="outline"
            className="h-10 w-full bg-white text-slate-700"
            disabled={!canSubmit}
            onClick={onSubmit}
            data-testid="first-run-submit-run"
          >
            {submitting ? <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" /> : <Play strokeWidth={1.5} className="mr-2 h-4 w-4" />}
            提交运行
          </Button>
          <div className="text-[11px] leading-4 text-slate-400">
            {localReady
              ? `${sampleUploads.length} 个输入已上传`
              : cacheReady
                ? "官方样例 cache 已验证，提交时会上传到 runner"
                : "使用官方三文件样例作为唯一输入来源"}
          </div>
        </div>
      </div>

      {submitError ? (
        <Alert variant="destructive" className="mt-4">
          <AlertCircle strokeWidth={1.5} className="h-4 w-4" />
          <AlertDescription>{submitError}</AlertDescription>
        </Alert>
      ) : null}
    </section>
  );
}

function useWorkflowSampleDataStatus({
  enabled,
  pipelineId,
  refreshKey,
}: {
  enabled: boolean;
  pipelineId: string;
  refreshKey: string;
}) {
  const [status, setStatus] = useState<WorkflowSampleDataStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!enabled) {
      setStatus(null);
      setLoading(false);
      setError("");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    fetchWorkflowSampleDataStatus(pipelineId)
      .then((nextStatus) => {
        if (!cancelled) setStatus(nextStatus);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "读取样例数据状态失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, pipelineId, refreshKey]);
  return { error, loading, status };
}

function SampleDataStatusPanel({
  error,
  loading,
  ready,
  sampleCacheEvidence,
  status,
}: {
  error: string;
  loading: boolean;
  ready: boolean;
  sampleCacheEvidence?: FirstRunStatusEvidence["sampleCache"];
  status: WorkflowSampleDataStatus | null;
}) {
  const summary = useMemo(
    () => sampleDataStatusSummary(status, ready, loading, error, sampleCacheEvidence),
    [error, loading, ready, sampleCacheEvidence, status]
  );
  return (
    <div
      className={cn("mt-3 rounded-md border px-3 py-2 text-xs leading-5", sampleDataStatusToneClass(summary.tone))}
      data-testid="first-run-sample-data-status"
      data-sample-data-status={summary.state}
    >
      <div className="flex min-w-0 items-center justify-between gap-3">
        <div className="min-w-0 font-semibold">{summary.label}</div>
        <span className="shrink-0 font-mono text-[11px]">{summary.countLabel}</span>
      </div>
      <div className="mt-1">{summary.detail}</div>
      {status?.items?.length ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {status.items.map((item) => (
            <span key={`${item.role}-${item.filename}`} className="rounded border border-current/20 bg-white/60 px-1.5 py-0.5 font-mono text-[10px]">
              {item.role}:{item.cacheStatus}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function sampleDataStatusSummary(
  status: WorkflowSampleDataStatus | null,
  ready: boolean,
  loading: boolean,
  error: string,
  sampleCacheEvidence?: FirstRunStatusEvidence["sampleCache"]
) {
  if (sampleCacheEvidence) {
    const countLabel = `${sampleCacheEvidence.verifiedCacheCount || 0}/${sampleCacheEvidence.itemCount || 0} cache`;
    if (sampleCacheEvidence.status === "ready") {
      return {
        countLabel,
        detail: "官方样例已在本机 cache 通过 checksum 校验；提交运行时会上传到 runner 并写入 prep proof。",
        label: "样例数据 cache 已验证",
        state: "ready",
        tone: "success" as const,
      };
    }
    if (sampleCacheEvidence.status === "blocked") {
      const blockers = sampleCacheEvidence.blockerCodes?.length
        ? sampleCacheEvidence.blockerCodes.join(" / ")
        : "样例缓存未通过校验。";
      return {
        countLabel,
        detail: blockers,
        label: "样例数据 readiness 阻断",
        state: "blocked",
        tone: "danger" as const,
      };
    }
    return {
      countLabel,
      detail: `${sampleCacheEvidence.missingCacheCount || 0} 个文件需要从官方来源下载并校验后上传。`,
      label: "样例数据需要官方来源",
      state: "source_required",
      tone: "info" as const,
    };
  }
  if (loading) {
    return {
      countLabel: "checking",
      detail: "正在读取官方三文件样例的本地 verified cache 状态。",
      label: "样例数据 readiness 检查中",
      state: "checking",
      tone: "warning" as const,
    };
  }
  if (error) {
    return {
      countLabel: "unavailable",
      detail: error,
      label: "无法读取样例数据 readiness",
      state: "unavailable",
      tone: "danger" as const,
    };
  }
  if (!status) {
    return {
      countLabel: ready ? "uploaded" : "pending",
      detail: ready ? "官方样例上传已通过角色和 checksum 校验。" : "等待确认 Moving Pictures 16S 样例 readiness。",
      label: ready ? "样例输入已就绪" : "样例数据 readiness 待确认",
      state: ready ? "ready" : "pending",
      tone: ready ? "success" as const : "warning" as const,
    };
  }
  const countLabel = `${status.verifiedCacheCount || 0}/${status.itemCount || 0} cache`;
  if (ready && status.status !== "blocked") {
    return {
      countLabel,
      detail: "官方样例已上传并通过角色与 checksum 校验；cache 状态仅影响下次准备速度。",
      label: "样例输入已就绪",
      state: "ready",
      tone: "success" as const,
    };
  }
  if (status.status === "blocked") {
    const blockers = status.blockerCodes?.length ? status.blockerCodes.join(" / ") : "样例缓存未通过校验。";
    return {
      countLabel,
      detail: blockers,
      label: "样例数据 readiness 阻断",
      state: "blocked",
      tone: "danger" as const,
    };
  }
  if (status.status === "ready") {
    return {
      countLabel,
      detail: `${status.source || "Official sample data"} 已在本机 cache 通过 checksum 校验，可直接上传到 runner。`,
      label: "样例数据 cache 已验证",
      state: "ready",
      tone: "success" as const,
    };
  }
  return {
    countLabel,
    detail: `${status.missingCacheCount || 0} 个文件需要从官方来源下载并校验后上传。`,
    label: "样例数据需要官方来源",
    state: "source_required",
    tone: "info" as const,
  };
}

function sampleDataStatusToneClass(tone: "success" | "warning" | "danger" | "info") {
  if (tone === "success") return "border-emerald-200 bg-emerald-50 text-emerald-900";
  if (tone === "danger") return "border-red-200 bg-red-50 text-red-900";
  if (tone === "info") return "border-blue-200 bg-blue-50 text-blue-900";
  return "border-amber-200 bg-amber-50 text-amber-900";
}

export function sampleUploadsReady(uploads: WorkflowUpload[]) {
  const roleAudit = sampleUploadRoleAudit(uploads);
  return (
    roleAudit.missingRoles.length === 0 &&
    roleAudit.unexpectedRoles.length === 0 &&
    roleAudit.duplicateRoles.length === 0 &&
    FIRST_RUN_EXPECTED_SAMPLE_ROLES.every((role) => {
      const upload = uploads.find((item) => item.role === role);
      return upload ? sampleIntegrityPassed(upload) : false;
    })
  );
}

export function sampleUploadRoleAudit(uploads: WorkflowUpload[]) {
  const roles = uploads.map((item) => item.role || "").filter(Boolean);
  const expectedRoles = new Set<string>(FIRST_RUN_EXPECTED_SAMPLE_ROLES);
  const roleCounts = new Map<string, number>();
  roles.forEach((role) => roleCounts.set(role, (roleCounts.get(role) || 0) + 1));
  return {
    missingRoles: FIRST_RUN_EXPECTED_SAMPLE_ROLES.filter((role) => !roles.includes(role)),
    unexpectedRoles: Array.from(new Set(roles.filter((role) => !expectedRoles.has(role)))),
    duplicateRoles: Array.from(roleCounts.entries())
      .filter(([, count]) => count > 1)
      .map(([role]) => role),
  };
}

function sampleUploadRoleBlockers(audit: ReturnType<typeof sampleUploadRoleAudit>) {
  return [
    audit.missingRoles.length ? `missing roles: ${audit.missingRoles.join(", ")}` : "",
    audit.unexpectedRoles.length ? `unexpected roles: ${audit.unexpectedRoles.join(", ")}` : "",
    audit.duplicateRoles.length ? `duplicate roles: ${audit.duplicateRoles.join(", ")}` : "",
  ].filter(Boolean);
}

function firstRunWorkflowSelection(workflow: WorkflowCatalogItem | null, loading: boolean) {
  if (loading && !workflow) {
    return {
      detail: "正在从 workflow catalog 读取首跑示例。",
      label: "正在确认 Moving Pictures 16S 示例",
      state: "loading",
      tone: "warning" as const,
    };
  }
  if (!workflow) {
    return {
      detail: "workflow catalog 缺少 moving-pictures-16s-rulegraph-v1，首跑不会退回到其他流程。",
      label: "未找到 Moving Pictures 16S 示例",
      state: "missing",
      tone: "danger" as const,
    };
  }
  if (!workflow.runnable) {
    return {
      detail: [workflow.status, workflow.source, workflow.version].filter(Boolean).join(" / ") || "该示例还未达到 WorkflowReady。",
      label: "示例存在但未 WorkflowReady",
      state: "blocked",
      tone: "danger" as const,
    };
  }
  return {
    detail: `${workflow.name || "Moving Pictures 16S"} 已作为首跑唯一示例。`,
    label: "已选择 Moving Pictures 16S 示例",
    state: "selected",
    tone: "success" as const,
  };
}

function sampleRoleLabel(role: string) {
  if (role === "metadata") return "sample metadata";
  if (role === "barcodes") return "barcode reads";
  if (role === "sequences") return "sequence reads";
  return role;
}

function sampleRoleFilename(role: string) {
  if (role === "metadata") return "sample-metadata.tsv";
  if (role === "barcodes") return "barcodes.fastq.gz";
  if (role === "sequences") return "sequences.fastq.gz";
  return role;
}

function sampleIntegrityLabel(upload: WorkflowUpload) {
  const hash = upload.sha256 || upload.expectedSha256 || "";
  const size = upload.expectedSizeBytes || upload.sizeBytes;
  return [hash ? `sha ${hash.slice(0, 12)}` : "", size ? formatBytes(size) : ""].filter(Boolean).join(" / ");
}

function samplePrepProofLabel(upload: WorkflowUpload) {
  const proof = upload.prepProof;
  if (!proof) return "prep proof pending";
  const cache = proof.cacheStatus ? `cache ${proof.cacheStatus}` : "";
  const download = proof.downloadStatus ? `${proof.downloadStatus} (${proof.downloadAttempts || 0} attempts)` : "";
  return [cache, download].filter(Boolean).join(" / ");
}

function sampleIntegrityPassed(upload: WorkflowUpload) {
  return upload.integrityStatus === "passed" && Boolean(upload.sha256) && upload.sha256 === upload.expectedSha256;
}
