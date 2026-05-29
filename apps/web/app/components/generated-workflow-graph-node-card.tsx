import { cn } from "@/lib/utils";

import type { AddedTool } from "./tools-page-model";
import {
  describePortSpec,
  readRuleInputs,
  readRuleOutputs,
  type RuleInputSpec,
  type RuleOutputSpec,
} from "./generated-workflow-model";
import type { GeneratedWorkflowBuilderController } from "./use-generated-workflow-builder";

export function RuleGraphNodeCard({
  edges,
  node,
  onSelect,
  selected,
  tool,
}: {
  edges: GeneratedWorkflowBuilderController["graphDraft"]["edges"];
  node: GeneratedWorkflowBuilderController["graphDraft"]["nodes"][number];
  onSelect: () => void;
  selected: boolean;
  tool: AddedTool | undefined;
}) {
  return (
    <button
      type="button"
      className={cn(
        "grid min-h-28 gap-2 rounded-md border bg-white px-3 py-2 text-left",
        selected ? "border-blue-300 ring-2 ring-blue-100" : "border-slate-200"
      )}
      onClick={onSelect}
      data-testid="rule-graph-node-card"
    >
      <span className="min-w-0">
        <span className="block truncate font-mono text-xs text-slate-800">{node.id}</span>
        <span className="block truncate text-[11px] text-slate-500">{tool?.name || node.toolId}</span>
      </span>
      <span className="grid gap-2 sm:grid-cols-2">
        <RulePortColumn direction="input" edges={edges} node={node} ports={readRuleInputs(tool)} />
        <RulePortColumn direction="output" edges={edges} node={node} ports={readRuleOutputs(tool)} />
      </span>
    </button>
  );
}

function RulePortColumn({
  direction,
  edges,
  node,
  ports,
}: {
  direction: "input" | "output";
  edges: GeneratedWorkflowBuilderController["graphDraft"]["edges"];
  node: GeneratedWorkflowBuilderController["graphDraft"]["nodes"][number];
  ports: Array<RuleInputSpec | RuleOutputSpec>;
}) {
  return (
    <span className="min-w-0">
      <span className="mb-1 block text-[10px] font-semibold uppercase text-slate-400">
        {direction === "input" ? "输入端口" : "输出端口"}
      </span>
      <span className="grid gap-1" data-port-direction={direction}>
        {ports.length === 0 ? (
          <span className="rounded border border-dashed border-slate-200 px-2 py-1 text-[10px] text-slate-400">
            {direction === "input" ? "无输入端口" : "无输出端口"}
          </span>
        ) : ports.slice(0, 3).map((port) => {
          const state = direction === "input"
            ? portBindingState(node, edges, port as RuleInputSpec)
            : outputFanoutState(node, edges, port as RuleOutputSpec);
          return (
          <span
            key={port.name}
            className="grid min-w-0 grid-cols-[6px_minmax(0,1fr)] items-center gap-1 rounded bg-slate-50 px-1.5 py-1"
            data-port-state={state.state}
          >
            <span className={cn("h-1.5 w-1.5 rounded-full", direction === "input" ? "bg-blue-400" : "bg-emerald-400")} />
            <span className="min-w-0">
              <span className="block truncate font-mono text-[10px] text-slate-700">{port.name}</span>
              <span className="block truncate text-[10px] text-slate-400">{describePortSpec(port)}</span>
              <span className={cn("block truncate text-[10px]", state.state === "unbound" ? "text-amber-500" : "text-slate-400")}>
                {state.label}
              </span>
              {port.capabilityLabel ? (
                <span className="block truncate text-[10px] text-violet-500" title={`能力来源: ${port.capabilityLabel}`}>
                  能力来源 · {port.capabilityLabel}
                </span>
              ) : null}
            </span>
          </span>
        );
        })}
      </span>
    </span>
  );
}

function portBindingState(
  node: GeneratedWorkflowBuilderController["graphDraft"]["nodes"][number],
  edges: GeneratedWorkflowBuilderController["graphDraft"]["edges"],
  port: RuleInputSpec
) {
  const connected = edges.some((edge) => edge.to.nodeId === node.id && edge.to.port === port.name);
  const localBinding = node.inputs[port.name];
  if (connected || Boolean(localBinding)) {
    return { state: "bound", label: "已连接" };
  }
  if (port.required === false) {
    return { state: "optional", label: "可选未绑定" };
  }
  return { state: "unbound", label: "待绑定" };
}

function outputFanoutState(
  node: GeneratedWorkflowBuilderController["graphDraft"]["nodes"][number],
  edges: GeneratedWorkflowBuilderController["graphDraft"]["edges"],
  port: RuleOutputSpec
) {
  const fanout = outputFanoutCount(node, edges, port);
  return { state: fanout > 0 ? "bound" : "available", label: fanout > 0 ? `fan-out ${fanout}` : "可连接" };
}

function outputFanoutCount(
  node: GeneratedWorkflowBuilderController["graphDraft"]["nodes"][number],
  edges: GeneratedWorkflowBuilderController["graphDraft"]["edges"],
  port: RuleOutputSpec
) {
  return edges.filter((edge) => edge.from.nodeId === node.id && edge.from.port === port.name).length;
}
