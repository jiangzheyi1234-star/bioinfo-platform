import { cn } from "@/lib/utils";

import type { AddedTool } from "./tools-page-model";
import {
  describePortSpec,
  readRuleInputs,
  readRuleOutputs,
  type GeneratedWorkflowValidationIssue,
  type RuleInputSpec,
  type RuleOutputSpec,
} from "./generated-workflow-model";
import type { GeneratedWorkflowBuilderController } from "./use-generated-workflow-builder";

type RulePortState = {
  state: "available" | "bound" | "error" | "optional" | "unbound";
  label: string;
  issue?: GeneratedWorkflowValidationIssue;
};

export function RuleGraphNodeCard({
  edges,
  node,
  onSelect,
  selected,
  tool,
  validationIssues,
}: {
  edges: GeneratedWorkflowBuilderController["graphDraft"]["edges"];
  node: GeneratedWorkflowBuilderController["graphDraft"]["nodes"][number];
  onSelect: () => void;
  selected: boolean;
  tool: AddedTool | undefined;
  validationIssues: GeneratedWorkflowValidationIssue[];
}) {
  const hasIssues = validationIssues.length > 0;
  return (
    <button
      type="button"
      className={cn(
        "grid min-h-28 gap-2 rounded-md border bg-white px-3 py-2 text-left",
        hasIssues ? "border-red-200 bg-red-50/40" : "border-slate-200",
        selected ? "ring-2 ring-blue-100" : ""
      )}
      onClick={onSelect}
      data-node-state={hasIssues ? "error" : "ready"}
      data-testid="rule-graph-node-card"
    >
      <span className="min-w-0">
        <span className="block truncate font-mono text-xs text-slate-800">{node.id}</span>
        <span className="block truncate text-[11px] text-slate-500">{tool?.name || node.toolId}</span>
        {hasIssues ? <span className="block truncate text-[10px] text-red-500">contract error · {validationIssues.length}</span> : null}
      </span>
      <span className="grid gap-2 sm:grid-cols-2">
        <RulePortColumn direction="input" edges={edges} node={node} ports={readRuleInputs(tool)} validationIssues={validationIssues} />
        <RulePortColumn direction="output" edges={edges} node={node} ports={readRuleOutputs(tool)} validationIssues={validationIssues} />
      </span>
    </button>
  );
}

function RulePortColumn({
  direction,
  edges,
  node,
  ports,
  validationIssues,
}: {
  direction: "input" | "output";
  edges: GeneratedWorkflowBuilderController["graphDraft"]["edges"];
  node: GeneratedWorkflowBuilderController["graphDraft"]["nodes"][number];
  ports: Array<RuleInputSpec | RuleOutputSpec>;
  validationIssues: GeneratedWorkflowValidationIssue[];
}) {
  const visiblePorts = ports.slice(0, 3);
  const unknownInputIssues = direction === "input" ? inputIssuesWithoutPorts(validationIssues, visiblePorts) : [];
  return (
    <span className="min-w-0">
      <span className="mb-1 block text-[10px] font-semibold uppercase text-slate-400">
        {direction === "input" ? "输入端口" : "输出端口"}
      </span>
      <span className="grid gap-1" data-port-direction={direction}>
        {ports.length === 0 && unknownInputIssues.length === 0 ? (
          <span className="rounded border border-dashed border-slate-200 px-2 py-1 text-[10px] text-slate-400">
            {direction === "input" ? "无输入端口" : "无输出端口"}
          </span>
        ) : (
          <>
          {visiblePorts.map((port) => {
            const state = direction === "input"
              ? portBindingState(node, edges, port as RuleInputSpec, issueForPort(validationIssues, port.name))
              : outputFanoutState(node, edges, port as RuleOutputSpec);
            return (
              <span
                key={port.name}
                className={cn(
                  "grid min-w-0 grid-cols-[6px_minmax(0,1fr)] items-center gap-1 rounded px-1.5 py-1",
                  state.state === "error" ? "bg-red-50" : "bg-slate-50"
                )}
                data-port-error={state.issue?.code || ""}
                data-port-state={state.state}
              >
                <span
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    state.state === "error" ? "bg-red-500" : direction === "input" ? "bg-blue-400" : "bg-emerald-400"
                  )}
                />
                <span className="min-w-0">
                  <span className="block truncate font-mono text-[10px] text-slate-700">{port.name}</span>
                  <span className="block truncate text-[10px] text-slate-400">{describePortSpec(port)}</span>
                  <span
                    className={cn(
                      "block truncate text-[10px]",
                      state.state === "error" ? "text-red-500" :
                      state.state === "unbound" ? "text-amber-500" : "text-slate-400"
                    )}
                  >
                    {state.label}
                  </span>
                </span>
              </span>
            );
          })
          }
          {unknownInputIssues.map((issue) => (
            <span
              key={`${issue.code}-${issue.inputName}`}
              className="grid min-w-0 grid-cols-[6px_minmax(0,1fr)] items-center gap-1 rounded bg-red-50 px-1.5 py-1"
              data-port-error={issue.code}
              data-port-state="error"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
              <span className="min-w-0">
                <span className="block truncate font-mono text-[10px] text-red-700">{issue.inputName}</span>
                <span className="block truncate text-[10px] text-red-500">未知输入端口</span>
                <span className="block truncate text-[10px] text-red-400">{issue.message}</span>
              </span>
            </span>
          ))}
          </>
        )}
      </span>
    </span>
  );
}

function portBindingState(
  node: GeneratedWorkflowBuilderController["graphDraft"]["nodes"][number],
  edges: GeneratedWorkflowBuilderController["graphDraft"]["edges"],
  port: RuleInputSpec,
  issue?: GeneratedWorkflowValidationIssue
): RulePortState {
  if (issue) {
    return { state: "error", label: issue.message, issue };
  }
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

function issueForPort(validationIssues: GeneratedWorkflowValidationIssue[], portName: string) {
  return validationIssues.find((issue) => issue.inputName === portName);
}

function inputIssuesWithoutPorts(
  validationIssues: GeneratedWorkflowValidationIssue[],
  ports: Array<RuleInputSpec | RuleOutputSpec>
) {
  const portNames = new Set(ports.map((port) => port.name));
  return validationIssues.filter((issue) => issue.inputName && !portNames.has(issue.inputName));
}

function outputFanoutState(
  node: GeneratedWorkflowBuilderController["graphDraft"]["nodes"][number],
  edges: GeneratedWorkflowBuilderController["graphDraft"]["edges"],
  port: RuleOutputSpec
): RulePortState {
  const fanout = outputFanoutCount(node, edges, port);
  return {
    state: fanout > 0 ? "bound" : "available",
    label: fanout > 0 ? `fan-out ${fanout}` : "可连接",
  };
}

function outputFanoutCount(
  node: GeneratedWorkflowBuilderController["graphDraft"]["nodes"][number],
  edges: GeneratedWorkflowBuilderController["graphDraft"]["edges"],
  port: RuleOutputSpec
) {
  return edges.filter((edge) => edge.from.nodeId === node.id && edge.from.port === port.name).length;
}
