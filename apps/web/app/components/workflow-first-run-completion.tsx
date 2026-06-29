"use client";

import { ArrowRight, CheckCircle2, CircleAlert, ClipboardCheck, Database, FileArchive, FileText, Loader2, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { FirstRunPilotHandoff, FirstRunValidationCard } from "./workflow-first-run-api";
import { FirstRunTrustSummary } from "./workflow-first-run-trust-summary";
import { firstRunResultPackageReady, formatBytes } from "./workflow-first-run-validation";
import { workflowResultPackageDownloadHref } from "./workflows-page-api";
import type { WorkflowResultPackageExport, WorkflowRun, WorkflowScenarioPack } from "./workflows-page-model";

export function FirstRunCompletionPanel({
  card,
  downloadingValidationCard,
  latestPackage,
  loadingValidationCard,
  onDownloadValidationCard,
  onDownloadValidationCardMarkdown,
  onDownloadHandoffManifest,
  nextScenarioPacks = [],
  nextScenarioPacksError = "",
  nextScenarioPacksLoading = false,
  pilotHandoff,
  ready,
  resultId,
  run,
  workflowRevisionId,
}: {
  card: FirstRunValidationCard | null;
  downloadingValidationCard: boolean;
  latestPackage?: WorkflowResultPackageExport;
  loadingValidationCard: boolean;
  nextScenarioPacks?: WorkflowScenarioPack[];
  nextScenarioPacksError?: string;
  nextScenarioPacksLoading?: boolean;
  onDownloadValidationCard: () => void;
  onDownloadValidationCardMarkdown: () => void;
  onDownloadHandoffManifest: () => void;
  pilotHandoff?: FirstRunPilotHandoff | null;
  ready: boolean;
  resultId: string;
  run: WorkflowRun | null;
  workflowRevisionId: string;
}) {
  if (!ready) return null;

  const downloadHref =
    latestPackage && firstRunResultPackageReady(latestPackage) ? workflowResultPackageDownloadHref(latestPackage) : "";
  const checks = card?.checks || [];
  const passedChecks = checks.filter((item) => item.status === "passed").length;
  const keyResults = card?.keyResults || [];
  const handoff = pilotHandoff || card?.pilotHandoff || null;
  const evidenceBundle = handoff?.evidenceBundle;

  return (
    <section
      className="rounded-lg border border-emerald-200 bg-emerald-50 p-5"
      data-testid="first-run-completion-panel"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-emerald-950">
            <CheckCircle2 strokeWidth={1.5} className="h-4 w-4 text-emerald-600" />
            首跑已完成
          </div>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-emerald-800">
            Moving Pictures 16S 已生成可下载结果包、验证卡和证据包清单。下载并分享以下 4 个文件，并保持它们放在一起。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {downloadHref ? (
            <Button asChild className="h-9 bg-slate-950 px-3 text-xs text-white hover:bg-slate-800">
              <a href={downloadHref} download={latestPackage?.download?.filename || undefined}>
                <FileArchive strokeWidth={1.5} className="mr-2 h-3.5 w-3.5" />
                下载结果包
              </a>
            </Button>
          ) : null}
          <Button
            variant="outline"
            className="h-9 border-emerald-200 bg-white px-3 text-xs text-emerald-800 hover:bg-emerald-50"
            disabled={downloadingValidationCard}
            onClick={onDownloadValidationCardMarkdown}
            data-testid="first-run-completion-download-card-markdown"
          >
            {downloadingValidationCard ? (
              <Loader2 strokeWidth={1.5} className="mr-2 h-3.5 w-3.5 animate-spin" />
            ) : (
              <FileText strokeWidth={1.5} className="mr-2 h-3.5 w-3.5" />
            )}
            下载验证卡 Markdown
          </Button>
          <Button
            variant="outline"
            className="h-9 border-emerald-200 bg-white px-3 text-xs text-emerald-800 hover:bg-emerald-50"
            disabled={downloadingValidationCard}
            onClick={onDownloadHandoffManifest}
            data-testid="first-run-completion-download-handoff"
          >
            {downloadingValidationCard ? (
              <Loader2 strokeWidth={1.5} className="mr-2 h-3.5 w-3.5 animate-spin" />
            ) : (
              <ClipboardCheck strokeWidth={1.5} className="mr-2 h-3.5 w-3.5" />
            )}
            下载证据包清单
          </Button>
          <Button
            variant="outline"
            className="h-9 border-emerald-200 bg-white px-3 text-xs text-emerald-800 hover:bg-emerald-50"
            disabled={downloadingValidationCard}
            onClick={onDownloadValidationCard}
            data-testid="first-run-completion-download-card"
          >
            {downloadingValidationCard ? (
              <Loader2 strokeWidth={1.5} className="mr-2 h-3.5 w-3.5 animate-spin" />
            ) : (
              <ClipboardCheck strokeWidth={1.5} className="mr-2 h-3.5 w-3.5" />
            )}
            下载验证卡 JSON
          </Button>
        </div>
      </div>

      {evidenceBundle ? <EvidenceBundleSummary bundle={evidenceBundle} /> : null}

      <div className="mt-4 grid gap-x-5 gap-y-2 border-t border-emerald-200 pt-4 text-xs md:grid-cols-2 xl:grid-cols-4">
        <SummaryItem label="run" value={run?.runId} mono />
        <SummaryItem label="result" value={resultId} mono />
        <SummaryItem label="revision" value={shortHash(workflowRevisionId)} mono />
        <SummaryItem label="package" value={latestPackage?.packageExportId} mono />
        <SummaryItem label="size" value={formatBytes(latestPackage?.sizeBytes)} />
        <SummaryItem label="package sha" value={shortHash(latestPackage?.sha256)} mono />
        <SummaryItem label="manifest" value={shortHash(latestPackage?.manifestSha256)} mono />
        <SummaryItem label="checks" value={checksLabel({ loadingValidationCard, passedChecks, totalChecks: checks.length })} />
      </div>

      {keyResults.length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-2" data-testid="first-run-completion-key-results">
          {keyResults.slice(0, 5).map((item) => (
            <span
              key={item.artifactId || item.displayName || item.artifactKey}
              className="inline-flex max-w-full items-center gap-1 rounded border border-emerald-200 bg-white px-2 py-1 text-[11px] text-slate-600"
            >
              <ShieldCheck strokeWidth={1.5} className="h-3 w-3 shrink-0 text-emerald-500" />
              <span className="truncate">{item.displayName || item.artifactKey || item.artifactId}</span>
              {item.sha256 ? <span className="font-mono text-slate-400">{shortHash(item.sha256)}</span> : null}
            </span>
          ))}
        </div>
      ) : null}

      <div className="mt-4">
        <FirstRunTrustSummary card={card} packageExport={latestPackage} />
      </div>

      {handoff ? <PilotHandoffSummary handoff={handoff} /> : null}
      <NextScenarioPilotSummary
        error={nextScenarioPacksError}
        loading={nextScenarioPacksLoading}
        packs={nextScenarioPacks}
      />
    </section>
  );
}

export function firstRunValidationCardPassed(card: FirstRunValidationCard | null) {
  const checks = card?.checks || [];
  const requiredBundleRoles = ["result-package", "validation-card-json", "validation-card-markdown", "pilot-handoff"];
  const bundleFiles = card?.pilotHandoff?.evidenceBundle?.requiredFiles || [];
  const bundleReady =
    card?.pilotHandoff?.evidenceBundle?.status === "ready" &&
    requiredBundleRoles.every((role) => bundleFiles.some((item) => item.role === role && item.filename));
  return (
    Boolean(card) &&
    checks.length > 0 &&
    checks.every((item) => item.status === "passed") &&
    card?.reportInterpretation?.status === "ready" &&
    card?.sampleData?.status === "verified" &&
    card?.softwareEnvironment?.status === "verified" &&
    Boolean(card?.pilotHandoff?.backupRestore) &&
    bundleReady &&
    Boolean(card?.resultPackage?.sha256) &&
    Boolean(card?.resultPackage?.manifestSha256)
  );
}

function SummaryItem({ label, mono = false, value }: { label: string; mono?: boolean; value?: string }) {
  if (!value) return null;
  return (
    <div className="grid min-w-0 grid-cols-[78px_minmax(0,1fr)] gap-2">
      <span className="text-emerald-700">{label}</span>
      <span className={cn("truncate text-emerald-950", mono ? "font-mono text-[11px]" : "")}>{value}</span>
    </div>
  );
}

function checksLabel({
  loadingValidationCard,
  passedChecks,
  totalChecks,
}: {
  loadingValidationCard: boolean;
  passedChecks: number;
  totalChecks: number;
}) {
  if (totalChecks > 0) return `${passedChecks}/${totalChecks} passed checks`;
  return loadingValidationCard ? "生成中" : "等待服务端验证卡";
}

function shortHash(value?: string) {
  return value ? value.slice(0, 12) : "";
}

function PilotHandoffSummary({ handoff }: { handoff: FirstRunPilotHandoff }) {
  const evidence = handoff.evidence || {};
  const nextAction = handoff.nextAction || {};
  const exclusions = handoff.exclusions || [];
  return (
    <div className="mt-4 border-t border-emerald-200 pt-4" data-testid="first-run-pilot-handoff">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-semibold text-emerald-950">单用户试点交接</div>
          <div className="mt-1 text-xs leading-5 text-emerald-800">
            {handoff.scope || "single-user-lab"} / {handoff.status || "ready"}
          </div>
        </div>
        {nextAction.target ? (
          <Button asChild variant="outline" className="h-8 border-emerald-200 bg-white px-2.5 text-xs text-emerald-800">
            <a href={nextAction.target}>{nextAction.label || nextAction.code || "下一步"}</a>
          </Button>
        ) : null}
      </div>
      <div className="mt-3 grid gap-x-5 gap-y-2 text-xs md:grid-cols-2 xl:grid-cols-4">
        <SummaryItem label="package" value={evidence.packageExportId} mono />
        <SummaryItem label="package sha" value={shortHash(evidence.packageSha256)} mono />
        <SummaryItem label="manifest" value={shortHash(evidence.manifestSha256)} mono />
        <SummaryItem label="checks" value={handoffChecksLabel(evidence)} />
      </div>
      {exclusions.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {exclusions.map((item) => (
            <span key={item} className="rounded border border-emerald-200 bg-white px-2 py-1 text-[11px] text-emerald-800">
              not {item}
            </span>
          ))}
        </div>
      ) : null}
      {handoff.backupRestore ? <PilotBackupRestoreSummary handoff={handoff} /> : null}
    </div>
  );
}

function EvidenceBundleSummary({ bundle }: { bundle: NonNullable<FirstRunPilotHandoff["evidenceBundle"]> }) {
  const requiredFiles = bundle.requiredFiles || [];
  return (
    <div className="mt-3 grid gap-2 text-xs" data-testid="first-run-evidence-bundle">
      <div className="flex flex-wrap items-center gap-2 text-emerald-950">
        <FileArchive strokeWidth={1.5} className="h-3.5 w-3.5 text-emerald-600" />
        <span className="font-semibold">可信证据包</span>
        <span className="text-emerald-700">{bundle.status || "ready"}</span>
        <span className="text-emerald-700">{requiredFiles.length} files</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {requiredFiles.map((item) => (
          <div
            key={item.role || item.filename}
            className="min-w-0 rounded border border-emerald-200 bg-white px-2 py-1 text-[11px]"
            data-testid="first-run-evidence-bundle-file"
          >
            <div className="truncate font-semibold text-emerald-800">{item.role || "evidence"}</div>
            <div className="truncate font-mono text-slate-500">{item.filename || item.source}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function PilotBackupRestoreSummary({ handoff }: { handoff: FirstRunPilotHandoff }) {
  const backup = handoff.backupRestore;
  if (!backup) return null;
  return (
    <div className="mt-3 grid gap-1 text-xs" data-testid="first-run-pilot-backup-restore">
      <SummaryItem label="backup" value={backup.planCommand} mono />
      <SummaryItem label="restore" value={backup.restoreProofCommand} mono />
    </div>
  );
}

function handoffChecksLabel(evidence: NonNullable<FirstRunPilotHandoff["evidence"]>) {
  if (typeof evidence.validationChecksPassed === "number" && typeof evidence.validationChecksTotal === "number") {
    return `${evidence.validationChecksPassed}/${evidence.validationChecksTotal} passed`;
  }
  return "";
}

function NextScenarioPilotSummary({
  error,
  loading,
  packs,
}: {
  error: string;
  loading: boolean;
  packs: WorkflowScenarioPack[];
}) {
  const blockedPacks = packs.filter((pack) => pack.status !== "ready").slice(0, 2);
  if (!loading && !error && blockedPacks.length === 0) return null;
  return (
    <div className="mt-4 border-t border-emerald-200 pt-4" data-testid="first-run-next-scenario-handoff">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-semibold text-emerald-950">下一批垂直试点</div>
          <div className="mt-1 text-xs leading-5 text-emerald-800">
            首跑已证明闭环；taxonomy 和 AMR 仍需按 checklist 补齐工具、样例和数据库证据后再运行。
          </div>
        </div>
        {loading ? <Loader2 strokeWidth={1.5} className="h-4 w-4 animate-spin text-emerald-700" /> : null}
      </div>
      {error ? <div className="mt-2 text-xs text-red-700">{error}</div> : null}
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        {blockedPacks.map((pack) => (
          <NextScenarioPilotCard key={pack.packId} pack={pack} />
        ))}
      </div>
    </div>
  );
}

function NextScenarioPilotCard({ pack }: { pack: WorkflowScenarioPack }) {
  const blockers = pack.readinessChecks.filter((item) => item.status !== "passed").slice(0, 3);
  const packOptions = pack.databaseHandoff?.packOptions || [];
  const missingTemplates = pack.databaseHandoff?.missingPackTemplates || [];
  const toolEvidence = pack.toolSliceHandoff?.promotionContract?.requiredEvidence || [];
  const readyScan = pack.databaseHandoff?.readyScan;
  const registration = pack.databaseHandoff?.registration;
  return (
    <article className="rounded-md border border-emerald-200 bg-white px-3 py-3" data-next-scenario={pack.scenarioId}>
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-xs font-semibold text-slate-950">{pack.name}</div>
          <div className="mt-1 truncate font-mono text-[11px] text-slate-400">{pack.pipelineId}</div>
        </div>
        <span className="shrink-0 rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">
          blocked
        </span>
      </div>
      <div className="mt-2 grid gap-1" data-testid="first-run-next-scenario-blockers">
        {blockers.map((item) => (
          <div key={item.code} className="flex min-w-0 items-center gap-1.5 text-[11px] text-slate-600">
            <CircleAlert strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-amber-500" />
            <span className="truncate">{item.requirement}</span>
          </div>
        ))}
      </div>
      <div className="mt-2 grid gap-1 text-[11px]" data-testid="first-run-next-scenario-database-handoff">
        {toolEvidence.length > 0 ? (
          <div className="truncate text-slate-500" data-testid="first-run-next-scenario-tool-slice-promotion">
            Tool evidence: {toolEvidence.slice(0, 4).join(" / ")}
          </div>
        ) : null}
        {packOptions.slice(0, 1).map((item) => (
          <div key={item.packId || item.templateId} className="flex min-w-0 items-center gap-1.5 text-slate-600">
            <Database strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
            <span className="truncate">{item.packId || item.name}</span>
            {item.checksum ? <span className="font-mono text-slate-400">{shortHash(item.checksum)}</span> : null}
          </div>
        ))}
        {missingTemplates.length > 0 ? (
          <div className="truncate text-amber-700">缺少官方 pack: {missingTemplates.slice(0, 3).join(" / ")}</div>
        ) : null}
        {readyScan?.path ? (
          <div className="truncate text-slate-500" data-testid="first-run-next-scenario-ready-scan">
            Ready scan: {readyScan.method || "POST"} {readyScan.path}
          </div>
        ) : null}
        {registration?.prefillSource ? (
          <div className="truncate text-slate-500" data-testid="first-run-next-scenario-registration-prefill">
            Prefill: {registration.prefillSource}
          </div>
        ) : null}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {pack.toolSliceHandoff?.operatorActionRequired ? (
          <Button asChild variant="outline" className="h-8 border-emerald-200 bg-white px-2.5 text-xs text-emerald-800" data-next-scenario-tool-action>
            <a href="/workflows/tools">
              <ClipboardCheck strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
              工具验收
            </a>
          </Button>
        ) : null}
        {pack.databaseHandoff?.operatorActionRequired ? (
          <Button asChild variant="outline" className="h-8 border-emerald-200 bg-white px-2.5 text-xs text-emerald-800" data-next-scenario-database-action>
            <a href="/workflows/databases">
              <Database strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
              数据库陪跑
            </a>
          </Button>
        ) : null}
        {pack.nextActions.slice(0, 2).map((action) => (
          <Button key={action.code} asChild variant="outline" className="h-8 border-emerald-200 bg-white px-2.5 text-xs text-emerald-800">
            <a href={action.target}>
              <ArrowRight strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
              {action.label}
            </a>
          </Button>
        ))}
      </div>
    </article>
  );
}
