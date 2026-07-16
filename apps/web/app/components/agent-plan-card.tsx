import type { ReactElement, ReactNode } from "react";
import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  FileText,
  GitBranch,
  Network,
  ShieldCheck,
} from "lucide-react";

import { cn } from "@/lib/utils";

import {
  formatAgentBytes,
  shortAgentIdentity,
  type AgentPlanRevision,
  type AgentWorkflowNode,
} from "./agent-workbench-model";

export type AgentPlanCardProps = {
  parentPlan?: AgentPlanRevision | null;
  plan: AgentPlanRevision;
};

type ToolRow = {
  id: string;
  name: string;
  node?: AgentWorkflowNode;
  revisionId: string;
  version: string;
};

export function AgentPlanCard({ parentPlan = null, plan }: AgentPlanCardProps) {
  const draft = plan.proposal.draft;
  const inputs = draft.inputs || [];
  const toolRows = orderedTools(plan);
  const diff = planDifference(plan, parentPlan);

  return (
    <section
      className="rounded-xl border border-slate-200 bg-white"
      aria-labelledby="agent-plan-card-title"
      data-plan-generation={plan.planGeneration}
      data-plan-valid={plan.validation.valid ? "true" : "false"}
      data-testid="agent-plan-card"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <Network strokeWidth={1.5} className="h-4 w-4 shrink-0 text-slate-500" aria-hidden="true" />
            <h2 id="agent-plan-card-title" className="truncate text-sm font-semibold text-slate-950">
              结构化方案 · generation {plan.planGeneration}
            </h2>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {draft.metadata.name} · {plan.proposal.planner.adapterId}
          </p>
        </div>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
            plan.validation.valid
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-red-200 bg-red-50 text-red-700"
          )}
        >
          {plan.validation.valid ? (
            <CheckCircle2 strokeWidth={1.5} className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <AlertTriangle strokeWidth={1.5} className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          {plan.validation.valid ? "验证通过" : "验证受阻"}
        </span>
      </div>

      <div className="space-y-5 px-5 py-5">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <IdentityMetric label="Plan revision" value={plan.planRevisionId} />
          <IdentityMetric label="Draft" value={`${plan.draftId}@${plan.draftRevision}`} testId="agent-plan-draft" />
          <IdentityMetric label="Planner" value={`${plan.proposal.planner.adapterId}@${plan.proposal.planner.adapterVersion || "—"}`} />
          <IdentityMetric label="Created" value={formatDateTime(plan.createdAt)} />
        </div>

        <PlanSection icon={<FileText />} title="输入证据" count={inputs.length}>
          {inputs.length > 0 ? (
            <div className="grid gap-2">
              {inputs.map((input, index) => {
                const digest = inputDigest(input);
                const size = inputSize(input);
                const uploadId = inputUploadId(input);
                return (
                  <details
                    key={`${input.id}-${index}`}
                    className="group rounded-lg border border-slate-200 bg-slate-50/60"
                    data-testid="agent-plan-input"
                  >
                    <summary className="cursor-pointer list-none px-3 py-2.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-slate-300">
                      <span className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                        <span className="min-w-0">
                          <span className="block truncate text-xs font-medium text-slate-900">{input.filename || input.id}</span>
                          <span className="mt-0.5 block truncate font-mono text-[11px] text-slate-500">
                            {formatAgentBytes(size)} · sha256 {shortAgentIdentity(digest, 16)}
                          </span>
                        </span>
                        <span className="text-[11px] text-slate-400">展开完整摘要</span>
                      </span>
                    </summary>
                    <dl className="grid gap-2 border-t border-slate-200 bg-white px-3 py-3 text-xs sm:grid-cols-[92px_minmax(0,1fr)]">
                      <DetailTerm label="uploadId" value={uploadId} />
                      <DetailTerm label="role" value={input.role} />
                      <DetailTerm label="mime" value={input.mimeType} />
                      <DetailTerm label="path" value={input.path} />
                      <DetailTerm label="sha256" value={digest} breakAll testId="agent-plan-input-sha256" />
                    </dl>
                  </details>
                );
              })}
            </div>
          ) : (
            <EmptyText>方案没有声明输入。</EmptyText>
          )}
        </PlanSection>

        <PlanSection icon={<Boxes />} title="精确工具修订" count={toolRows.length}>
          <div className="grid gap-2 md:grid-cols-2">
            {toolRows.map((tool, index) => (
              <article
                key={`${tool.id}-${tool.revisionId}-${index}`}
                className="rounded-lg border border-slate-200 bg-slate-50/60 px-3 py-3"
                data-testid="agent-plan-tool"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-slate-900">{tool.name}</div>
                    <div className="mt-0.5 font-mono text-[11px] text-slate-500">step {tool.id}</div>
                  </div>
                  <span className="rounded border border-blue-200 bg-blue-50 px-2 py-0.5 font-mono text-[11px] text-blue-700">
                    {tool.version}
                  </span>
                </div>
                <div className="mt-2 break-all rounded-md bg-white px-2 py-1.5 font-mono text-[11px] text-slate-700">
                  {tool.revisionId}
                </div>
                {tool.node ? <NodeResourceSummary node={tool.node} /> : null}
              </article>
            ))}
          </div>
        </PlanSection>

        <PlanSection icon={<ShieldCheck />} title="Capability 证据" count={draft.nodes.length}>
          <div className="grid gap-2 md:grid-cols-2" data-testid="agent-capability-evidence">
            {draft.nodes.map((node) => (
              <div key={node.id} className="rounded-lg border border-slate-200 px-3 py-2.5 text-xs">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-slate-800">{node.id}</span>
                  <span className="font-mono text-[11px] text-emerald-700">
                    {scalar(node.metadata.toolVersion) || "version locked"}
                  </span>
                </div>
                <dl className="mt-2 grid gap-1 sm:grid-cols-[112px_minmax(0,1fr)]">
                  <DetailTerm label="bundle" value={scalar(node.metadata.capabilityBundleVersion)} />
                  <DetailTerm label="capability" value={scalar(node.metadata.capabilityId)} breakAll />
                  <DetailTerm label="selection" value={scalar(node.provenance.selection)} />
                  <DetailTerm label="source" value={scalar(node.provenance.source)} />
                </dl>
              </div>
            ))}
          </div>
        </PlanSection>

        <div className="grid gap-4 lg:grid-cols-2">
          <PlanSection icon={<Boxes />} title="资源与输出" count={draft.outputs.length} compact>
            <div className="space-y-3">
              <div>
                <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">Required resources</div>
                <CodeBlock value={plan.validation.requiredResources} fallback="无额外 resource binding" />
              </div>
              <div>
                <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">Exposed outputs</div>
                {draft.outputs.length > 0 ? (
                  <ul className="mt-2 grid gap-1.5" data-testid="agent-plan-outputs">
                    {draft.outputs.map((output) => (
                      <li key={`${output.from.nodeId}.${output.from.port}:${output.as}`} className="rounded-md bg-slate-50 px-2.5 py-2 text-xs">
                        <span className="font-medium text-slate-800">{output.as}</span>
                        <span className="ml-2 font-mono text-[11px] text-slate-500">
                          {output.from.nodeId}.{output.from.port}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <EmptyText>没有 exposed output。</EmptyText>
                )}
              </div>
            </div>
          </PlanSection>

          <PlanSection icon={<GitBranch />} title="不可变 lineage / diff" compact>
            <div data-testid="agent-plan-lineage">
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5">
                <div className="text-xs font-medium text-slate-800">{diff.title}</div>
                <div className="mt-1 font-mono text-[11px] text-slate-500">
                  {plan.parentPlanRevisionId || "no parent plan"}
                </div>
              </div>
              <ul className="mt-2 grid gap-1.5 text-xs text-slate-600">
                {diff.items.map((item) => (
                  <li key={item} className="rounded-md bg-white px-2 py-1.5">{item}</li>
                ))}
              </ul>
            </div>
          </PlanSection>
        </div>

        <PlanSection
          icon={plan.validation.valid ? <CheckCircle2 /> : <AlertTriangle />}
          title="Plan-only validation"
          count={plan.validation.validationIssues.length}
        >
          <div className="flex flex-wrap gap-1.5 text-[11px]">
            {(plan.validation.orderedSteps || []).map((step, index) => (
              <span key={`${step.id}-${index}`} className="rounded-full border border-slate-200 bg-slate-50 px-2 py-1 font-mono text-slate-600">
                {index + 1}. {step.id}
              </span>
            ))}
          </div>
          {plan.validation.validationIssues.length > 0 ? (
            <ul className="mt-3 grid gap-2" data-testid="agent-validation-issues">
              {plan.validation.validationIssues.map((issue, index) => (
                <li key={`${issue.code}-${index}`} className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
                  <div className="font-mono font-medium">{issue.code}</div>
                  <div className="mt-1">{issue.message}</div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-xs text-emerald-700">输入、端口、工具修订、资源和 exposed outputs 已通过现有 plan-only gate。</p>
          )}
        </PlanSection>

        <div className="rounded-lg border border-slate-200 bg-slate-950 px-4 py-3 text-slate-100" data-testid="agent-plan-hash">
          <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">Approval-bound planHash</div>
          <code className="mt-2 block break-all text-xs leading-5">{plan.planHash}</code>
        </div>

        <ExecutionGraph plan={plan} />
      </div>
    </section>
  );
}

function PlanSection({
  children,
  compact = false,
  count,
  icon,
  title,
}: {
  children: ReactNode;
  compact?: boolean;
  count?: number;
  icon: ReactElement;
  title: string;
}) {
  return (
    <section className={cn("rounded-xl border border-slate-200 bg-white", compact ? "p-4" : "p-4")}>
      <div className="mb-3 flex items-center gap-2">
        <span className="text-slate-500 [&>svg]:h-4 [&>svg]:w-4 [&>svg]:stroke-[1.5]" aria-hidden="true">{icon}</span>
        <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
        {typeof count === "number" ? <span className="text-xs text-slate-400">{count}</span> : null}
      </div>
      {children}
    </section>
  );
}

function IdentityMetric({ label, testId, value }: { label: string; testId?: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2" data-testid={testId}>
      <div className="text-[11px] font-medium text-slate-400">{label}</div>
      <div className="mt-1 truncate font-mono text-xs text-slate-800" title={value}>{value}</div>
    </div>
  );
}

function DetailTerm({
  breakAll = false,
  label,
  testId,
  value,
}: {
  breakAll?: boolean;
  label: string;
  testId?: string;
  value: string;
}) {
  return (
    <>
      <dt className="text-slate-400">{label}</dt>
      <dd className={cn("min-w-0 font-mono text-slate-700", breakAll ? "break-all" : "truncate")} data-testid={testId}>
        {value || "—"}
      </dd>
    </>
  );
}

function NodeResourceSummary({ node }: { node: AgentWorkflowNode }) {
  const scheduler = node.runtime.schedulerResources || {};
  const resources = Object.keys(node.resources || {}).length > 0 ? node.resources : scheduler;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-slate-500">
      <span className="rounded border border-slate-200 bg-white px-1.5 py-0.5">threads {node.runtime.threads ?? "—"}</span>
      {Object.entries(resources).map(([key, value]) => (
        <span key={key} className="rounded border border-slate-200 bg-white px-1.5 py-0.5">{key} {scalar(value)}</span>
      ))}
    </div>
  );
}

function CodeBlock({ fallback, value }: { fallback: string; value: Record<string, unknown> }) {
  const hasValue = Object.keys(value || {}).length > 0;
  return (
    <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-md bg-slate-50 px-2.5 py-2 font-mono text-[11px] leading-5 text-slate-600">
      {hasValue ? stableJson(value, 2) : fallback}
    </pre>
  );
}

function ExecutionGraph({ plan }: { plan: AgentPlanRevision }) {
  const draft = plan.proposal.draft;
  return (
    <details
      className="rounded-xl border border-slate-200 bg-slate-50/50"
      data-read-only="true"
      data-testid="agent-execution-graph"
    >
      <summary className="cursor-pointer list-none px-4 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-slate-300">
        <span className="flex flex-wrap items-center justify-between gap-2">
          <span className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <GitBranch strokeWidth={1.5} className="h-4 w-4 text-slate-500" aria-hidden="true" />
            高级：Execution graph（只读）
          </span>
          <span className="text-xs text-slate-500">{draft.nodes.length} nodes · {draft.edges.length} edges</span>
        </span>
      </summary>
      <div className="border-t border-slate-200 px-4 py-4">
        <p className="text-xs leading-5 text-slate-500">
          这是供专家审查、编译和 lineage 使用的确定性投影；不支持拖拽、连线或参数编辑。
        </p>
        <ol className="mt-3 grid gap-2" aria-label="Execution graph 节点">
          {draft.nodes.map((node, index) => (
            <li key={node.id} className="rounded-lg border border-slate-200 bg-white px-3 py-3" data-testid="agent-execution-graph-node">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium text-slate-900">{index + 1}. {node.id}</span>
                <span className="font-mono text-[11px] text-slate-500">{node.toolRevisionId}</span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-slate-500">
                {Object.keys(node.inputs || {}).map((name) => <span key={`in-${name}`} className="rounded bg-slate-50 px-2 py-1">in:{name}</span>)}
                {Object.keys(node.outputs || {}).map((name) => <span key={`out-${name}`} className="rounded bg-emerald-50 px-2 py-1 text-emerald-700">out:{name}</span>)}
              </div>
            </li>
          ))}
        </ol>
        {draft.edges.length > 0 ? (
          <ul className="mt-3 grid gap-1.5" aria-label="Execution graph 依赖边">
            {draft.edges.map((edge, index) => (
              <li key={edge.id || index} className="rounded-md bg-white px-3 py-2 font-mono text-xs text-slate-600" data-testid="agent-execution-graph-edge">
                {edge.from.nodeId}.{edge.from.port} → {edge.to.nodeId}.{edge.to.port}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </details>
  );
}

function planDifference(plan: AgentPlanRevision, parent: AgentPlanRevision | null) {
  if (!plan.parentPlanRevisionId) {
    return {
      title: "初始方案",
      items: [
        `${plan.proposal.draft.nodes.length} 个工具节点`,
        `${plan.proposal.draft.inputs.length} 个输入`,
        `${plan.proposal.draft.outputs.length} 个 exposed outputs`,
      ],
    };
  }
  if (!parent || parent.planRevisionId !== plan.parentPlanRevisionId) {
    return {
      title: "父方案引用已保留",
      items: ["父方案快照尚未加载；不会把当前方案误报为初始方案。"],
    };
  }
  const currentDraft = plan.proposal.draft;
  const parentDraft = parent.proposal.draft;
  const currentNodes = new Map(currentDraft.nodes.map((node) => [node.id, node]));
  const parentNodes = new Map(parentDraft.nodes.map((node) => [node.id, node]));
  const added = [...currentNodes.keys()].filter((id) => !parentNodes.has(id));
  const removed = [...parentNodes.keys()].filter((id) => !currentNodes.has(id));
  const changed = [...currentNodes.keys()].filter((id) => {
    const before = parentNodes.get(id);
    return before && stableJson(before) !== stableJson(currentNodes.get(id));
  });
  return {
    title: `相对 ${shortAgentIdentity(parent.planRevisionId, 18)}`,
    items: [
      `节点：+${added.length} / -${removed.length} / changed ${changed.length}`,
      `输入：${parentDraft.inputs.length} → ${currentDraft.inputs.length}`,
      `输出：${parentDraft.outputs.length} → ${currentDraft.outputs.length}`,
      `planHash changed: ${parent.planHash === plan.planHash ? "no" : "yes"}`,
    ],
  };
}

function orderedTools(plan: AgentPlanRevision): ToolRow[] {
  const nodes = new Map(plan.proposal.draft.nodes.map((node) => [node.id, node]));
  const steps = plan.validation.orderedSteps || [];
  if (steps.length === 0) {
    return plan.proposal.draft.nodes.map((node) => toolRow(node.id, node, node.toolRevisionId, node.id));
  }
  return steps.map((step) => {
    const node = nodes.get(step.id);
    return toolRow(
      step.id,
      node,
      step.toolRevisionId || node?.toolRevisionId || "missing revision",
      step.toolName || step.rule || step.id
    );
  });
}

function toolRow(id: string, node: AgentWorkflowNode | undefined, revisionId: string, name: string): ToolRow {
  return {
    id,
    name,
    node,
    revisionId,
    version: scalar(node?.metadata.toolVersion) || "version locked",
  };
}

function inputDigest(input: AgentPlanRevision["proposal"]["draft"]["inputs"][number]) {
  return metadataString(input.metadata, "sha256");
}

function inputSize(input: AgentPlanRevision["proposal"]["draft"]["inputs"][number]) {
  const value = input.metadata.sizeBytes;
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function inputUploadId(input: AgentPlanRevision["proposal"]["draft"]["inputs"][number]) {
  return metadataString(input.metadata, "uploadId");
}

function metadataString(metadata: Record<string, unknown>, key: string) {
  const value = metadata[key];
  return typeof value === "string" ? value : "";
}

function scalar(value: unknown) {
  if (value === undefined || value === null || value === "") return "";
  if (["string", "number", "boolean"].includes(typeof value)) return String(value);
  return stableJson(value);
}

function stableJson(value: unknown, space?: number): string {
  return JSON.stringify(sortJson(value), null, space) ?? "";
}

function sortJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortJson);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, nested]) => [key, sortJson(nested)])
  );
}

function EmptyText({ children }: { children: ReactNode }) {
  return <p className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-400">{children}</p>;
}

function formatDateTime(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}
