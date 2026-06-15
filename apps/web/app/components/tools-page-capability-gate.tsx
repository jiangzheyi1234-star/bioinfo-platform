import { Check, Database } from "lucide-react";

import type { CapabilityBundleGate } from "./tools-page-model";

export function CapabilityBundleGatePanel({ gate }: { gate?: CapabilityBundleGate | null }) {
  const total = gate?.total ?? 0;
  if (total <= 0) return null;
  const blockedTools = gate?.blockedTools ?? [];
  return (
    <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2 text-xs font-medium text-slate-800">
          <Check strokeWidth={1.5} className="h-4 w-4 text-emerald-600" />
          <span>Capability bundle</span>
          <span className="font-mono text-slate-500">
            {gate?.selectable ?? 0}/{total} agent selectable
          </span>
        </div>
        {gate?.blocked ? (
          <span className="text-xs text-amber-700">{gate.blocked} blocked</span>
        ) : (
          <span className="text-xs text-emerald-700">ready</span>
        )}
      </div>
      {blockedTools.length > 0 ? (
        <div className="mt-2 grid gap-1.5">
          {blockedTools.slice(0, 4).map((tool) => {
            const databaseHref = databaseAdmissionHref(tool);
            return (
              <div
                key={`${tool.toolRevisionId || tool.toolId || tool.capabilityId}`}
                className="flex min-w-0 flex-wrap items-center gap-2 text-xs"
              >
                <span className="max-w-[220px] truncate font-mono text-slate-700">{tool.toolId || tool.toolRevisionId}</span>
                <span className="rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-700">
                  {capabilityBlockedReasonLabel(tool.blockedReasons)}
                </span>
                {tool.nextAction === "add-database" ? (
                  <a
                    href={databaseHref}
                    className="inline-flex items-center gap-1 text-[11px] font-medium text-blue-700 hover:text-blue-900"
                  >
                    <Database strokeWidth={1.5} className="h-3 w-3" />
                    添加数据库
                  </a>
                ) : (
                  <span className="text-[11px] text-slate-500">{capabilityNextActionLabel(tool.nextAction)}</span>
                )}
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

function databaseAdmissionHref(tool: NonNullable<CapabilityBundleGate["blockedTools"]>[number]) {
  const template = tool.admissionEvidence?.missingResources?.[0]?.acceptedTemplates?.[0]?.trim();
  if (!template) return "/workflows/databases";
  return `/workflows/databases?template=${encodeURIComponent(template)}`;
}

function capabilityBlockedReasonLabel(reasons?: string[]) {
  if (reasons?.includes("DATABASE_RESOURCE_REQUIRED")) return "缺少已验证数据库";
  if (reasons?.includes("CAPABILITY_APPROVAL_REQUIRED")) return "需要审批";
  if (reasons?.includes("VALIDATION_EVIDENCE_REQUIRED")) return "需要验证";
  return reasons?.[0] || "未满足准入";
}

function capabilityNextActionLabel(action?: string) {
  if (action === "request-approval") return "请求审批";
  if (action === "run-validation") return "运行验证";
  if (action === "lock-environment") return "锁定环境";
  if (action === "complete-capability-bundle") return "补齐 bundle";
  return action || "待处理";
}
