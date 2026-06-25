"use client";

import { useMemo, useState } from "react";
import { CheckCircle2, Database, FileInput, FileOutput, GitBranch, Loader2, Settings, UploadCloud } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import type { JsonSchemaProperty, WorkflowArtifact, WorkflowCatalogItem, WorkflowRunDetail, WorkflowRunRule, WorkflowUpload } from "./workflows-page-model";

type WorkflowDagPreviewProps = {
  workflow: WorkflowCatalogItem | null;
  sampleLoading?: boolean;
  sampleUploads?: WorkflowUpload[];
  files?: File[];
  params?: Record<string, unknown>;
  onParamsChange?: (values: Record<string, unknown>) => void;
  onLoadSampleData?: () => void;
  runDetail?: WorkflowRunDetail | null;
};

export function WorkflowDagPreview({
  workflow,
  sampleLoading = false,
  sampleUploads = [],
  files = [],
  params = {},
  onParamsChange,
  onLoadSampleData,
  runDetail,
}: WorkflowDagPreviewProps) {
  if (!workflow) return null;

  const graph = readWorkflowGraph(workflow);
  if (graph) {
    return (
      <WorkflowRuleGraph
        files={files}
        graph={graph}
        onLoadSampleData={onLoadSampleData}
        onParamsChange={onParamsChange}
        params={params}
        runDetail={runDetail}
        sampleLoading={sampleLoading}
        sampleUploads={sampleUploads}
        workflow={workflow}
      />
    );
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex items-center justify-between gap-4">
        <h3 className="text-sm font-semibold text-slate-900">流程 DAG</h3>
        <div className="text-xs text-slate-400">{workflow.engine || "workflow"}</div>
      </div>
      <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        该流程缺少 <span className="font-mono">uiSchema.graph</span>，无法展示真实 Snakemake DAG。
      </div>
    </div>
  );
}

type GraphArtifact = {
  kind?: string;
  name?: string;
  mimeType?: string;
};

type GraphNode = {
  id: string;
  label: string;
  kind?: "input" | "rule" | "output" | string;
  detail?: string;
  group?: string;
  title?: string;
  description?: string;
  role?: string;
  params?: string[];
  artifacts?: GraphArtifact[];
  operationHints?: string[];
  inputs?: string[];
  outputs?: string[];
  members?: GraphNode[];
  runtimeStatusKey?: string;
  resourceHints?: Record<string, unknown>;
  retryPolicy?: Record<string, unknown>;
};

type GraphEdge = {
  from: string;
  to: string;
};

type WorkflowGraph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

function readWorkflowGraph(workflow: WorkflowCatalogItem): WorkflowGraph | null {
  const graph = (workflow.uiSchema?.graph || null) as Partial<WorkflowGraph> | null;
  if (!graph || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) return null;
  const nodes = graph.nodes
    .filter((node) => node && typeof node.id === "string" && typeof node.label === "string")
    .map((node) => ({
      id: node.id,
      label: node.label,
      kind: node.kind || "rule",
      group: node.group || node.kind || "rule",
      title: node.title || node.label,
      description: node.description || node.detail || "",
      detail: node.detail || "",
      role: typeof node.role === "string" ? node.role : "",
      params: Array.isArray(node.params) ? node.params.filter((item): item is string => typeof item === "string") : [],
      artifacts: Array.isArray(node.artifacts) ? node.artifacts.filter((item) => item && typeof item === "object") : [],
      operationHints: Array.isArray(node.operationHints) ? node.operationHints.filter((item): item is string => typeof item === "string") : [],
      inputs: Array.isArray(node.inputs) ? node.inputs.filter((item): item is string => typeof item === "string") : [],
      outputs: Array.isArray(node.outputs) ? node.outputs.filter((item): item is string => typeof item === "string") : [],
      runtimeStatusKey: typeof node.runtimeStatusKey === "string" ? node.runtimeStatusKey : "",
      resourceHints: isRecord(node.resourceHints) ? node.resourceHints : undefined,
      retryPolicy: isRecord(node.retryPolicy) ? node.retryPolicy : undefined,
    }));
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = graph.edges
    .filter((edge) => edge && nodeIds.has(edge.from) && nodeIds.has(edge.to))
    .map((edge) => ({ from: edge.from, to: edge.to }));
  if (nodes.length === 0 || edges.length === 0) return null;
  return { nodes, edges };
}

function nodeIcon(kind?: string) {
  if (kind === "input") return <FileInput strokeWidth={1.5} className="h-3.5 w-3.5" />;
  if (kind === "output") return <FileOutput strokeWidth={1.5} className="h-3.5 w-3.5" />;
  if (kind === "database") return <Database strokeWidth={1.5} className="h-3.5 w-3.5" />;
  return <Settings strokeWidth={1.5} className="h-3.5 w-3.5" />;
}

const GROUPS = [
  { key: "input", title: "输入数据", tone: "border-blue-100 bg-blue-50/40 text-blue-800", dot: "bg-blue-500" },
  { key: "validation", title: "元数据校验", tone: "border-violet-100 bg-violet-50/40 text-violet-800", dot: "bg-violet-500" },
  { key: "demultiplex", title: "样本拆分", tone: "border-cyan-100 bg-cyan-50/40 text-cyan-800", dot: "bg-cyan-500" },
  { key: "qc", title: "质量控制", tone: "border-amber-100 bg-amber-50/50 text-amber-800", dot: "bg-amber-500" },
  { key: "feature", title: "特征构建", tone: "border-emerald-100 bg-emerald-50/40 text-emerald-800", dot: "bg-emerald-500" },
  { key: "analysis", title: "分析步骤", tone: "border-sky-100 bg-sky-50/40 text-sky-800", dot: "bg-sky-500" },
  { key: "merge", title: "合并步骤", tone: "border-rose-100 bg-rose-50/40 text-rose-800", dot: "bg-rose-500" },
  { key: "database", title: "数据库依赖", tone: "border-slate-200 bg-slate-50 text-slate-700", dot: "bg-slate-400" },
  { key: "report", title: "汇总报告", tone: "border-indigo-100 bg-indigo-50/40 text-indigo-800", dot: "bg-indigo-500" },
  { key: "output", title: "结果产物", tone: "border-teal-100 bg-teal-50/40 text-teal-800", dot: "bg-teal-500" },
];

const GROUP_BY_KEY = new Map(GROUPS.map((group) => [group.key, group]));

function groupConfig(group?: string) {
  return GROUP_BY_KEY.get(group || "") || {
    key: group || "rule",
    title: group || "规则",
    tone: "border-slate-200 bg-slate-50 text-slate-800",
    dot: "bg-slate-400",
  };
}

function isInputNode(node: GraphNode) {
  return node.kind === "input";
}

function isOutputNode(node: GraphNode) {
  return node.kind === "output";
}

function isProcessNode(node: GraphNode) {
  return !isInputNode(node) && !isOutputNode(node);
}

function nodeKindLabel(node: GraphNode) {
  if (node.kind === "rule") return "rule";
  if (node.kind === "input" || node.kind === "output") return "聚合";
  return groupConfig(node.group || node.kind).title;
}

function topologicalProcessNodes(graph: WorkflowGraph): GraphNode[] {
  const processNodes = graph.nodes.filter(isProcessNode);
  const processIds = new Set(processNodes.map((node) => node.id));
  const originalIndex = new Map(processNodes.map((node, index) => [node.id, index]));
  const incomingCount = new Map(processNodes.map((node) => [node.id, 0]));
  const outgoing = new Map(processNodes.map((node) => [node.id, [] as string[]]));

  for (const edge of graph.edges) {
    if (!processIds.has(edge.from) || !processIds.has(edge.to)) continue;
    outgoing.get(edge.from)?.push(edge.to);
    incomingCount.set(edge.to, (incomingCount.get(edge.to) || 0) + 1);
  }

  const queue = processNodes
    .filter((node) => (incomingCount.get(node.id) || 0) === 0)
    .sort((left, right) => (originalIndex.get(left.id) || 0) - (originalIndex.get(right.id) || 0));
  const ordered: GraphNode[] = [];

  while (queue.length > 0) {
    const current = queue.shift();
    if (!current) break;
    ordered.push(current);
    for (const nextId of outgoing.get(current.id) || []) {
      const nextCount = (incomingCount.get(nextId) || 0) - 1;
      incomingCount.set(nextId, nextCount);
      if (nextCount === 0) {
        const next = processNodes.find((node) => node.id === nextId);
        if (next) {
          queue.push(next);
          queue.sort((left, right) => (originalIndex.get(left.id) || 0) - (originalIndex.get(right.id) || 0));
        }
      }
    }
  }

  if (ordered.length === processNodes.length) return ordered;

  const orderedIds = new Set(ordered.map((node) => node.id));
  return [...ordered, ...processNodes.filter((node) => !orderedIds.has(node.id))];
}

function buildMainFlowNodes(graph: WorkflowGraph, workflow: WorkflowCatalogItem): GraphNode[] {
  const inputNodes = graph.nodes.filter(isInputNode);
  const outputNodes = graph.nodes.filter(isOutputNode);
  const processNodes = topologicalProcessNodes(graph);
  const graphArtifacts = outputNodes.flatMap((node) => node.artifacts || []);
  const expectedArtifacts = graphArtifacts.length > 0 ? graphArtifacts : workflow.outputSchema?.artifacts || [];
  const inputTitles = inputNodes.map((node) => node.title || node.label).filter(Boolean);
  const outputTitles = outputNodes.map((node) => node.title || node.label).filter(Boolean);

  return [
    {
      id: "__inputs",
      label: "workflow inputs",
      title: "输入数据",
      kind: "input",
      group: "input",
      description: inputTitles.length > 0 ? `聚合 ${inputTitles.join("、")}。` : "聚合该流程声明的输入数据。",
      detail: `${inputNodes.length} files`,
      outputs: inputNodes.flatMap((node) => node.outputs || []),
      members: inputNodes,
      operationHints: ["sampleData"],
    },
    ...processNodes,
    {
      id: "__outputs",
      label: "workflow outputs",
      title: "结果产物",
      kind: "output",
      group: "output",
      description: outputTitles.length > 0 ? `聚合 ${outputTitles.join("、")}。` : "聚合该流程声明的结果产物。",
      detail: `${expectedArtifacts.length || outputNodes.flatMap((node) => node.inputs || []).length || 0} outputs`,
      inputs: outputNodes.flatMap((node) => node.inputs || []),
      artifacts: expectedArtifacts,
      members: outputNodes,
      operationHints: ["expectedOutputs"],
    },
  ];
}

function FlowNodeButton({
  index,
  node,
  onSelect,
  rule,
  selected,
}: {
  index: number;
  node: GraphNode;
  onSelect: () => void;
  rule?: WorkflowRunRule;
  selected: boolean;
}) {
  const group = groupConfig(node.group || node.kind);
  const isEndpoint = node.kind === "input" || node.kind === "output";
  const paramCount = node.params?.length || 0;
  const memberCount = node.members?.length || 0;
  const artifactCount = node.artifacts?.length || node.inputs?.length || 0;
  const caption = node.kind === "input"
    ? `${memberCount || node.outputs?.length || 0} 个输入`
    : node.kind === "output"
      ? `${artifactCount} 个产物`
      : paramCount > 0
        ? `可调参数 ${paramCount}`
        : group.title;

  return (
    <button
      type="button"
      aria-pressed={selected}
      data-dag-order={index + 1}
      data-testid={`dag-flow-node-${node.id}`}
      onClick={onSelect}
      className={cn(
        "group relative z-10 grid min-h-[86px] w-full min-w-0 grid-cols-[36px_minmax(0,1fr)_auto] items-start gap-3 rounded-lg border bg-white px-3 py-3 text-left transition hover:border-slate-300 hover:shadow-sm",
        isEndpoint ? "border-slate-200" : "border-slate-200/80",
        selected ? "border-slate-400 shadow-md ring-2 ring-slate-950/10" : "shadow-[0_1px_0_rgba(15,23,42,0.03)]"
      )}
    >
      <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-full border", group.tone)}>
        <span className="sr-only">{String(index + 1).padStart(2, "0")}</span>
        <span aria-hidden="true">
          {nodeIcon(node.kind)}
        </span>
      </span>
      <span className="min-w-0">
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <span className="min-w-0 truncate text-sm font-semibold leading-5 text-slate-950">{node.title || node.label}</span>
          <span className={cn("rounded border px-1.5 py-0.5 text-[10px]", group.tone)}>{nodeKindLabel(node)}</span>
          {rule ? <span className={cn("rounded border px-1.5 py-0.5 text-[10px]", runRuleStatusTone(rule.status))}>{rule.status}</span> : null}
        </span>
        <span className="mt-1 block truncate font-mono text-[11px] text-slate-400">{node.label}</span>
        <span className="mt-2 block line-clamp-1 text-xs leading-5 text-slate-600">{node.description || node.detail}</span>
      </span>
      <span className="flex shrink-0 flex-col items-end gap-2">
        <span className="font-mono text-[10px] text-slate-300">{String(index + 1).padStart(2, "0")}</span>
        <span className="inline-flex max-w-[96px] items-center gap-1.5 rounded-full bg-slate-50 px-2 py-1 text-[11px] text-slate-500">
          <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", group.dot)} />
          <span className="truncate">{caption}</span>
        </span>
      </span>
    </button>
  );
}

function FlowConnector({ done }: { done: boolean }) {
  return (
    <div className="relative z-0 ml-[17px] h-7 w-px bg-slate-200" aria-hidden="true">
      <div className={cn("absolute left-1/2 top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full border bg-white", done ? "border-slate-300" : "border-slate-200")} />
    </div>
  );
}

function FlowSummary({ flowNodes }: { flowNodes: GraphNode[] }) {
  const processCount = flowNodes.filter(isProcessNode).length;
  const inputCount = flowNodes.find((node) => node.kind === "input")?.members?.length || 0;
  const outputCount = flowNodes.find((node) => node.kind === "output")?.artifacts?.length || 0;
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 text-[11px] text-slate-500" data-testid="dag-flow-summary">
      <span className="rounded-full border border-blue-100 bg-blue-50 px-2.5 py-1 text-blue-700">输入聚合 {inputCount}</span>
      <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-600">执行步骤 {processCount}</span>
      <span className="rounded-full border border-teal-100 bg-teal-50 px-2.5 py-1 text-teal-700">输出聚合 {outputCount}</span>
    </div>
  );
}

function FlowRoadmap({
  flowNodes,
  onSelect,
  ruleByNodeId,
  selectedId,
}: {
  flowNodes: GraphNode[];
  onSelect: (nodeId: string) => void;
  ruleByNodeId: Map<string, WorkflowRunRule>;
  selectedId: string;
}) {
  const selectedIndex = flowNodes.findIndex((node) => node.id === selectedId);
  return (
    <div className="rounded-xl border border-slate-100 bg-slate-50/40 p-4" data-testid="dag-flow-roadmap">
      <FlowSummary flowNodes={flowNodes} />
      <div className="grid min-w-0 grid-cols-1">
        {flowNodes.map((node, index) => (
          <div key={node.id} className="min-w-0" data-testid={`dag-roadmap-step-${index + 1}`}>
            <FlowNodeButton index={index} node={node} rule={ruleByNodeId.get(node.id)} selected={selectedId === node.id} onSelect={() => onSelect(node.id)} />
            {index < flowNodes.length - 1 ? <FlowConnector done={index < selectedIndex} /> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function WorkflowRuleGraph({
  files,
  graph,
  onLoadSampleData,
  onParamsChange,
  params,
  runDetail,
  sampleLoading,
  sampleUploads,
  workflow,
}: Required<Pick<WorkflowDagPreviewProps, "files" | "sampleUploads" | "sampleLoading" | "params">> &
  Pick<WorkflowDagPreviewProps, "onLoadSampleData" | "onParamsChange" | "runDetail"> & {
    workflow: WorkflowCatalogItem;
    graph: WorkflowGraph;
}) {
  const flowNodes = useMemo(() => buildMainFlowNodes(graph, workflow), [graph, workflow]);
  const ruleByNodeId = useMemo(() => runRulesByGraphNode(flowNodes, runDetail), [flowNodes, runDetail]);
  const [selectedId, setSelectedId] = useState(() => flowNodes.find((node) => node.kind === "rule")?.id || flowNodes[0]?.id || "");
  const selectedNode = flowNodes.find((node) => node.id === selectedId) || flowNodes[0];
  const selectedRule = selectedNode ? ruleByNodeId.get(selectedNode.id) : undefined;
  const ruleCount = graph.nodes.filter((node) => node.kind === "rule").length;
  const run = runDetail?.run || null;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5" data-testid="workflow-dag-inspector">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">流程 DAG</h3>
          <div className="mt-1 text-xs text-slate-400">主流程地图 · 点击节点查看 Inspector</div>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <span>{workflow.engine || "snakemake"}</span>
          <span className="rounded bg-slate-50 px-2 py-1">规则 {ruleCount}</span>
          {run ? <span className="rounded bg-emerald-50 px-2 py-1 text-emerald-700">{run.stage || run.status}</span> : null}
        </div>
      </div>

      <div className="mt-5">
        <FlowRoadmap flowNodes={flowNodes} ruleByNodeId={ruleByNodeId} selectedId={selectedNode?.id || ""} onSelect={setSelectedId} />
      </div>

      {selectedNode ? (
        <NodeInspector
          files={files}
          node={selectedNode}
          onLoadSampleData={onLoadSampleData}
          onParamsChange={onParamsChange}
          params={params}
          rule={selectedRule}
          runDetail={runDetail}
          sampleLoading={sampleLoading}
          sampleUploads={sampleUploads}
          workflow={workflow}
        />
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3 text-[11px] text-slate-400">
        <GitBranch strokeWidth={1.5} className="h-3.5 w-3.5" />
        <span>{graph.edges.length} 条依赖边</span>
        <span>结构来自 manifest/Snakefile；这里只暴露可验证的运行配置。</span>
      </div>
    </div>
  );
}

function ChipRow({ label, values, compact = false }: { label: string; values: string[]; compact?: boolean }) {
  if (values.length === 0) return null;
  const shown = compact ? values.slice(0, 2) : values;
  const hidden = values.length - shown.length;
  return (
    <div className={cn("mt-2 flex min-w-0 flex-wrap items-center gap-1", compact ? "max-h-11 overflow-hidden" : "")}>
      {label ? <span className="text-[10px] text-slate-400">{label}</span> : null}
      {shown.map((value) => (
        <span key={`${label}-${value}`} className="max-w-full truncate rounded-md border border-white/70 bg-white/70 px-1.5 py-0.5 font-mono text-[10px] text-slate-600" title={value}>
          {value}
        </span>
      ))}
      {hidden > 0 ? <span className="rounded-md bg-white/60 px-1.5 py-0.5 text-[10px] text-slate-400">+{hidden}</span> : null}
    </div>
  );
}

function NodeInspector({
  files,
  node,
  onLoadSampleData,
  onParamsChange,
  params,
  rule,
  runDetail,
  sampleLoading,
  sampleUploads,
  workflow,
}: {
  files: File[];
  node: GraphNode;
  onLoadSampleData?: () => void;
  onParamsChange?: (values: Record<string, unknown>) => void;
  params: Record<string, unknown>;
  rule?: WorkflowRunRule;
  runDetail?: WorkflowRunDetail | null;
  sampleLoading: boolean;
  sampleUploads: WorkflowUpload[];
  workflow: WorkflowCatalogItem;
}) {
  const group = groupConfig(node.group || node.kind);
  const paramProperties = getParamProperties(workflow);

  return (
    <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50/60 p-4" data-testid="dag-node-inspector">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span className={cn("h-1.5 w-1.5 rounded-full", group.dot)} />
            <span>{group.title}</span>
            <span className="font-mono">{node.label}</span>
          </div>
          <h4 className="mt-1 text-base font-semibold text-slate-950">{node.title || node.label}</h4>
          {node.description ? <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">{node.description}</p> : null}
        </div>
        <span className={cn("rounded-md border px-2 py-1 text-xs", group.tone)}>{node.kind === "rule" ? "Snakemake rule" : group.title}</span>
      </div>

      <RuleRunStatus rule={rule} />

      {node.kind === "input" ? (
        <InputInspector files={files} node={node} onLoadSampleData={onLoadSampleData} sampleLoading={sampleLoading} sampleUploads={sampleUploads} />
      ) : node.kind === "output" ? (
        <OutputInspector node={node} runDetail={runDetail} workflow={workflow} />
      ) : (
        <RuleInspector node={node} onParamsChange={onParamsChange} paramProperties={paramProperties} params={params} />
      )}

      <NodeMetadata node={node} />
    </div>
  );
}

function runRulesByGraphNode(nodes: GraphNode[], runDetail?: WorkflowRunDetail | null) {
  const rules = runDetail?.rules?.items || [];
  const byRuntimeStatusKey = new Map(rules.filter((rule) => rule.runtimeStatusKey).map((rule) => [rule.runtimeStatusKey as string, rule]));
  const byStepId = new Map(rules.filter((rule) => rule.stepId).map((rule) => [rule.stepId as string, rule]));
  const byRuleName = new Map(rules.map((rule) => [rule.ruleName, rule]));
  const matched = new Map<string, WorkflowRunRule>();
  for (const node of nodes) {
    const rule =
      (node.runtimeStatusKey ? byRuntimeStatusKey.get(node.runtimeStatusKey) : undefined) ||
      byStepId.get(node.id) ||
      byStepId.get(node.label) ||
      byRuleName.get(node.id) ||
      byRuleName.get(node.label) ||
      byRuleName.get(node.title || "");
    if (rule) matched.set(node.id, rule);
  }
  return matched;
}

function runRuleStatusTone(status?: string) {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "completed" || normalized === "success" || normalized === "succeeded") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (normalized === "failed" || normalized === "error") return "border-red-200 bg-red-50 text-red-700";
  if (normalized === "running" || normalized === "started") return "border-blue-200 bg-blue-50 text-blue-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function RuleRunStatus({ rule }: { rule?: WorkflowRunRule }) {
  if (!rule) return null;
  const latest = (rule.events || []).slice(-1)[0];
  return (
    <div className="mt-4 rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className={cn("rounded border px-2 py-0.5 text-xs font-medium", runRuleStatusTone(rule.status))}>{rule.status}</span>
            <span className="truncate font-mono text-[11px] text-slate-500">{rule.ruleName}</span>
          </div>
          {rule.message || latest?.message ? <div className="mt-1 truncate text-xs text-slate-600">{rule.message || latest?.message}</div> : null}
        </div>
        <div className="grid grid-cols-3 gap-2 text-right text-[11px] text-slate-500">
          <span>attempt <b className="font-mono font-normal text-slate-700">{rule.attemptNumber ?? "—"}</b></span>
          <span>lease <b className="font-mono font-normal text-slate-700">{rule.leaseGeneration ?? "—"}</b></span>
          <span>exit <b className="font-mono font-normal text-slate-700">{rule.exitCode ?? "—"}</b></span>
        </div>
      </div>
    </div>
  );
}

function InputInspector({
  files,
  node,
  onLoadSampleData,
  sampleLoading,
  sampleUploads,
}: {
  files: File[];
  node: GraphNode;
  onLoadSampleData?: () => void;
  sampleLoading: boolean;
  sampleUploads: WorkflowUpload[];
}) {
  const inputNodes = node.members && node.members.length > 0 ? node.members : [node];
  const matchedUploads = inputNodes
    .map((item) => ({
      node: item,
      upload: item.role ? sampleUploads.find((upload) => upload.role === item.role) : null,
    }));
  const readyCount = matchedUploads.filter((item) => item.upload).length;
  return (
    <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
      <div className="rounded-lg bg-white p-3">
        <div className="text-xs font-medium text-slate-500">输入说明</div>
        <div className="mt-3 grid gap-2">
          {matchedUploads.map(({ node: inputNode, upload }) => (
            <div
              key={inputNode.id}
              className={cn(
                "grid gap-2 rounded-lg px-3 py-2 text-xs sm:grid-cols-[minmax(0,1fr)_auto]",
                upload ? "bg-emerald-50 text-emerald-800" : "bg-slate-50 text-slate-600"
              )}
            >
              <div className="min-w-0">
                <div className="truncate font-medium text-slate-800">{inputNode.title || inputNode.label}</div>
                <div className="truncate font-mono text-[11px] text-slate-500">{inputNode.outputs?.[0] || inputNode.detail || inputNode.label}</div>
              </div>
              <div className="flex min-w-0 items-center gap-1.5 justify-self-start sm:justify-self-end">
                {upload ? <CheckCircle2 strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0" /> : null}
                <span className="truncate font-mono text-[11px]">role: {inputNode.role || "未声明"}</span>
              </div>
              {upload ? (
                <div className="min-w-0 truncate font-mono text-[11px] sm:col-span-2">{upload.filename}</div>
              ) : null}
            </div>
          ))}
        </div>
        {readyCount === 0 ? (
          <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
            {files.length > 0 ? `已选择 ${files.length} 个手动文件，尚未绑定到这些 role。` : "还没有准备这些输入文件。"}
          </div>
        ) : null}
      </div>
      <div className="rounded-lg bg-white p-3">
        <div className="text-xs font-medium text-slate-500">操作</div>
        <Button type="button" variant="outline" className="mt-3 h-8 w-full bg-white text-xs" disabled={!onLoadSampleData || sampleLoading} onClick={onLoadSampleData}>
          {sampleLoading ? <Loader2 strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <UploadCloud strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />}
          准备官方示例数据
        </Button>
        <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
          已准备 {readyCount} / {inputNodes.length} 个输入
        </div>
        <p className="mt-2 text-[11px] leading-5 text-slate-400">示例数据会写入当前运行输入；DAG 不改变流程结构。</p>
      </div>
    </div>
  );
}

function RuleInspector({
  node,
  onParamsChange,
  paramProperties,
  params,
}: {
  node: GraphNode;
  onParamsChange?: (values: Record<string, unknown>) => void;
  paramProperties: Record<string, JsonSchemaProperty>;
  params: Record<string, unknown>;
}) {
  return (
    <div className="mt-4 grid gap-3 md:grid-cols-2">
      <div className="rounded-lg bg-white p-3">
        <div className="text-xs font-medium text-slate-500">输入 / 输出</div>
        <ChipRow label="输入" values={node.inputs || []} />
        <ChipRow label="输出" values={node.outputs || []} />
      </div>
      <div className="rounded-lg bg-white p-3">
        <div className="text-xs font-medium text-slate-500">影响该步骤的运行参数</div>
        {node.params && node.params.length > 0 ? (
          <div className="mt-3 grid gap-3">
            {node.params.map((key) => (
              <ParamEditor key={key} paramKey={key} property={paramProperties[key]} values={params} onChange={onParamsChange} />
            ))}
          </div>
        ) : (
          <p className="mt-3 text-xs leading-5 text-slate-500">这个 rule 暂无可安全暴露的运行参数。</p>
        )}
      </div>
    </div>
  );
}

function NodeMetadata({ node }: { node: GraphNode }) {
  const resources = recordEntries(node.resourceHints);
  const retry = recordEntries(node.retryPolicy);
  const hints = node.operationHints || [];
  if (!node.runtimeStatusKey && resources.length === 0 && retry.length === 0 && hints.length === 0) return null;

  return (
    <div className="mt-3 grid gap-3 md:grid-cols-3">
      {node.runtimeStatusKey ? (
        <div className="rounded-lg bg-white p-3">
          <div className="text-xs font-medium text-slate-500">运行状态键</div>
          <Chip value={node.runtimeStatusKey} />
        </div>
      ) : null}
      {resources.length > 0 ? (
        <MetadataCard title="资源提示" entries={resources} />
      ) : null}
      {retry.length > 0 ? (
        <MetadataCard title="重试策略" entries={retry} />
      ) : null}
      {hints.length > 0 ? (
        <div className="rounded-lg bg-white p-3">
          <div className="text-xs font-medium text-slate-500">操作提示</div>
          <ChipRow label="" values={hints} compact />
        </div>
      ) : null}
    </div>
  );
}

function MetadataCard({ title, entries }: { title: string; entries: string[] }) {
  return (
    <div className="rounded-lg bg-white p-3">
      <div className="text-xs font-medium text-slate-500">{title}</div>
      <ChipRow label="" values={entries} compact />
    </div>
  );
}

function OutputInspector({ node, runDetail, workflow }: { node: GraphNode; runDetail?: WorkflowRunDetail | null; workflow: WorkflowCatalogItem }) {
  const expected = node.artifacts && node.artifacts.length > 0 ? node.artifacts : workflow.outputSchema?.artifacts || [];
  const actual = runDetail?.results?.artifacts || [];
  return (
    <div className="mt-4 grid gap-3 md:grid-cols-2">
      <div className="rounded-lg bg-white p-3">
        <div className="text-xs font-medium text-slate-500">预计产物</div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {expected.map((artifact) => (
            <Chip key={`${artifact.kind}-${artifact.name || artifact.mimeType}`} value={`${artifact.name || "artifact"} · ${artifact.kind || artifact.mimeType || "file"}`} />
          ))}
        </div>
      </div>
      <div className="rounded-lg bg-white p-3">
        <div className="text-xs font-medium text-slate-500">最近运行产物</div>
        {actual.length > 0 ? (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {actual.slice(0, 6).map((artifact) => (
              <Chip key={artifact.artifactId} value={`${artifactName(artifact)} · ${artifact.kind || artifact.mimeType || "artifact"}`} />
            ))}
          </div>
        ) : (
          <p className="mt-3 text-xs leading-5 text-slate-500">还没有可展示的运行产物；提交并完成后会在这里出现概览。</p>
        )}
      </div>
    </div>
  );
}

function ParamEditor({
  onChange,
  paramKey,
  property,
  values,
}: {
  onChange?: (values: Record<string, unknown>) => void;
  paramKey: string;
  property?: JsonSchemaProperty;
  values: Record<string, unknown>;
}) {
  const label = property?.title || paramKey;
  const type = property?.type || "string";
  const value = values[paramKey] !== undefined ? values[paramKey] : property?.default ?? "";
  function updateValue(raw: string) {
    if (!onChange) return;
    const nextValue = type === "integer" ? parseInt(raw, 10) : type === "number" ? parseFloat(raw) : raw;
    onChange({ ...values, [paramKey]: raw === "" ? "" : nextValue });
  }
  return (
    <div className="space-y-1.5" data-testid={`dag-param-${paramKey}`}>
      <Label htmlFor={`dag-param-${paramKey}`} className="text-xs text-slate-700">{label}</Label>
      <Input
        id={`dag-param-${paramKey}`}
        type={type === "number" || type === "integer" ? "number" : "text"}
        min={property?.minimum}
        max={property?.maximum}
        value={String(value)}
        onChange={(event) => updateValue(event.target.value)}
        className="h-8 bg-white text-xs"
      />
      {property?.description ? <p className="text-[11px] text-slate-500">{property.description}</p> : null}
    </div>
  );
}

function Chip({ value }: { value: string }) {
  return <span className="max-w-full truncate rounded-md border border-slate-200 bg-slate-50 px-2 py-1 font-mono text-[11px] text-slate-600" title={value}>{value}</span>;
}

function getParamProperties(workflow: WorkflowCatalogItem) {
  const schema = workflow.paramsSchema && typeof workflow.paramsSchema === "object" ? workflow.paramsSchema : {};
  return ((schema.properties || {}) as Record<string, JsonSchemaProperty>) || {};
}

function artifactName(artifact?: WorkflowArtifact) {
  if (!artifact) return "artifact";
  return artifact.kind || artifact.mimeType || artifact.artifactId || "artifact";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function recordEntries(value?: Record<string, unknown>) {
  if (!value) return [];
  return Object.entries(value)
    .filter(([, item]) => item !== undefined && item !== null && item !== "")
    .map(([key, item]) => `${key}: ${String(item)}`);
}
