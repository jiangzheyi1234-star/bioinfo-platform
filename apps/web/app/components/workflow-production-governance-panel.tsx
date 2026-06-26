"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, RefreshCw, ShieldCheck, XCircle } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { fetchWorkflowServiceInfo } from "./workflow-service-info-api";
import type {
  WorkflowLocalServiceInfo,
  WorkflowProductionGovernanceCheck,
  WorkflowProductionGovernanceReadiness,
} from "./workflow-service-info-model";
import { workflowErrorMessage } from "./workflows-page-model";

export function WorkflowProductionGovernancePanel() {
  const [serviceInfo, setServiceInfo] = useState<WorkflowLocalServiceInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (forceRefresh = false) => {
    setLoading(true);
    setError("");
    try {
      setServiceInfo(await fetchWorkflowServiceInfo({ forceRefresh }));
    } catch (err) {
      setError(workflowErrorMessage(err, "读取生产治理 readiness 失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const governance = serviceInfo?.productionGovernance;
  const checks = governance?.checks || [];
  const summary = useMemo(() => productionGovernanceSummary(governance), [governance]);

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <ShieldCheck strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
          <div>
            <h2 className="text-sm font-semibold text-slate-900">生产治理 readiness</h2>
            <div className="mt-0.5 text-xs text-slate-500">
              {serviceInfo?.deployment?.mode || "mode unknown"} · {governance?.schemaVersion || "schema pending"}
            </div>
          </div>
        </div>
        <Button
          type="button"
          variant="outline"
          className="h-8 bg-white px-2.5 text-xs"
          disabled={loading}
          onClick={() => void load(true)}
        >
          {loading ? (
            <Loader2 strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
          )}
          刷新
        </Button>
      </div>

      {error ? (
        <Alert variant="destructive" className="mb-3 py-2 text-xs">
          <AlertCircle strokeWidth={1.5} className="h-3.5 w-3.5" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {!governance && loading ? (
        <div className="flex h-16 items-center justify-center text-sm text-slate-400">
          <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
          正在读取 readiness
        </div>
      ) : (
        <div className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <GovernanceMetric label="current" value={governance?.currentModeStatus || "—"} tone={statusTone(governance?.currentModeStatus)} />
            <GovernanceMetric label="multi-user" value={governance?.publicMultiUserStatus || "—"} tone="blocked" />
            <GovernanceMetric label="blocking" value={String(summary.publicBlockingCount)} tone={summary.publicBlockingCount ? "warn" : "pass"} />
            <GovernanceMetric label="checks" value={String(checks.length)} />
          </div>

          <div className="grid gap-2 lg:grid-cols-2">
            {checks.slice(0, 8).map((check, index) => (
              <GovernanceCheckRow key={check.id || `${check.reasonCode || "check"}:${index}`} check={check} />
            ))}
            {checks.length === 0 ? (
              <div className="rounded-md border border-slate-100 bg-slate-50 px-3 py-2 text-xs text-slate-400">
                暂无 readiness checks
              </div>
            ) : null}
          </div>

          {governance?.publicMultiUserBlockingCheckIds?.length ? (
            <div className="flex flex-wrap gap-1.5 border-t border-slate-100 pt-3">
              {governance.publicMultiUserBlockingCheckIds.slice(0, 12).map((id) => (
                <span key={id} className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">
                  {id}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

function GovernanceCheckRow({ check }: { check: WorkflowProductionGovernanceCheck }) {
  const tone = statusTone(check.status);
  const evidence = (check.evidence || []).slice(0, 2).join(", ");
  return (
    <div className="rounded-md border border-slate-100 bg-slate-50 px-3 py-2 text-xs">
      <div className="flex min-w-0 items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2">
          {tone === "pass" ? (
            <CheckCircle2 strokeWidth={1.5} className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
          ) : (
            <XCircle strokeWidth={1.5} className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
          )}
          <div className="min-w-0">
            <div className="truncate font-mono text-[11px] text-slate-800">{check.id || "check"}</div>
            <div className="mt-0.5 truncate text-slate-500">{check.reasonCode || "reason pending"}</div>
          </div>
        </div>
        <span className={cn("rounded border px-1.5 py-0.5 font-medium", statusClass(tone))}>
          {check.status || "unknown"}
        </span>
      </div>
      <div className="mt-1 grid gap-1 text-[11px] sm:grid-cols-[88px_minmax(0,1fr)]">
        <span className="text-slate-400">blocks</span>
        <span className="truncate font-mono text-slate-600">{check.blocksCurrentMode ? "current mode" : check.requiredFor || "—"}</span>
        <span className="text-slate-400">evidence</span>
        <span className="truncate font-mono text-slate-600">{evidence || "—"}</span>
      </div>
    </div>
  );
}

function GovernanceMetric({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "pass" | "warn" | "blocked";
}) {
  return (
    <div className={cn("rounded-md border px-3 py-2", statusClass(tone))}>
      <div className="text-[11px] font-medium text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold">{value}</div>
    </div>
  );
}

function productionGovernanceSummary(governance?: WorkflowProductionGovernanceReadiness) {
  return {
    publicBlockingCount: governance?.publicMultiUserBlockingCheckIds?.length || 0,
  };
}

function statusTone(status?: string): "default" | "pass" | "warn" | "blocked" {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "pass" || normalized === "ready" || normalized === "not_applicable") return "pass";
  if (normalized === "blocked") return "blocked";
  if (normalized === "pending" || normalized === "partial" || normalized === "degraded") return "warn";
  return "default";
}

function statusClass(tone: "default" | "pass" | "warn" | "blocked") {
  if (tone === "pass") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (tone === "warn") return "border-amber-200 bg-amber-50 text-amber-700";
  if (tone === "blocked") return "border-red-200 bg-red-50 text-red-700";
  return "border-slate-200 bg-white text-slate-700";
}
