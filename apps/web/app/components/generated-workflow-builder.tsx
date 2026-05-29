"use client";

import { useMemo, useState } from "react";
import { AlertCircle, Database, Plus, Trash2, Workflow } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import type { DatabaseItem } from "./database-page-model";
import type { AddedTool } from "./tools-page-model";
import {
  describePortSpec,
  readRuleInputs,
  readRuleOutputs,
  readRuleParams,
} from "./generated-workflow-model";
import { GeneratedWorkflowGraphCanvas } from "./generated-workflow-graph-canvas";
import { GeneratedWorkflowNodeSettings } from "./generated-workflow-node-settings";
import {
  GeneratedWorkflowPortBindingsEditor,
  type GeneratedWorkflowOutputCandidate,
} from "./generated-workflow-port-bindings-editor";
import { GeneratedWorkflowRuleSpecPanel } from "./generated-workflow-rule-spec-panel";
import { GeneratedWorkflowRuntimeEditor } from "./generated-workflow-runtime-editor";
import {
  GeneratedWorkflowGraphSnakefilePreview,
  GeneratedWorkflowSnakefilePreview,
} from "./generated-workflow-snakefile-preview";
import { StepParamsEditor } from "./generated-workflow-step-params-editor";
import type { GeneratedWorkflowBuilderController } from "./use-generated-workflow-builder";
import { databaseMatchesWorkflowResource } from "./workflows-page-model";

type GeneratedWorkflowBuilderProps = {
  builder: GeneratedWorkflowBuilderController;
  tools: AddedTool[];
  availableDatabases: DatabaseItem[];
  inputCount: number;
};

export function GeneratedWorkflowBuilder({
  builder,
  tools,
  availableDatabases,
  inputCount,
}: GeneratedWorkflowBuilderProps) {
  const firstTool = tools[0];
  const outputCandidates = buildOutputCandidates(builder.draft.steps, tools);

  return (
    <div className="space-y-5 border-t border-slate-100 px-5 py-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Workflow strokeWidth={1.5} className="h-4 w-4" />
            工具工作流
          </div>
          <div className="mt-1 text-xs text-slate-500">显式绑定每个步骤的输入、上游输出和暴露产物。</div>
        </div>
        <Button
          type="button"
          variant="outline"
          className="h-8 bg-white px-2.5 text-xs"
          disabled={!firstTool}
          onClick={() => firstTool && builder.addStep(firstTool.id)}
        >
          <Plus strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
          添加步骤
        </Button>
      </div>

      {builder.validation.errors.length > 0 ? (
        <Alert variant="destructive" className="py-2 text-xs">
          <AlertCircle strokeWidth={1.5} className="h-3.5 w-3.5" />
          <AlertDescription>
            {builder.validation.errors.slice(0, 3).map((error) => error.message).join("；")}
          </AlertDescription>
        </Alert>
      ) : null}

      <WorkflowGraphWorkbench
        builder={builder}
        nodes={builder.graphDraft.nodes}
        edges={builder.graphDraft.edges}
        inputCount={inputCount}
        outputCandidates={outputCandidates}
        tools={tools}
      />

      <OutputExposureEditor builder={builder} outputCandidates={outputCandidates} />
      <GeneratedResourceBindings builder={builder} availableDatabases={availableDatabases} />
    </div>
  );
}

function WorkflowGraphWorkbench({
  builder,
  nodes,
  edges,
  inputCount,
  outputCandidates,
  tools,
}: {
  builder: GeneratedWorkflowBuilderController;
  nodes: GeneratedWorkflowBuilderController["graphDraft"]["nodes"];
  edges: GeneratedWorkflowBuilderController["graphDraft"]["edges"];
  inputCount: number;
  outputCandidates: GeneratedWorkflowOutputCandidate[];
  tools: AddedTool[];
}) {
  const toolById = new Map(tools.map((tool) => [tool.id, tool]));
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === selectedNodeId) || nodes[0],
    [nodes, selectedNodeId]
  );
  const selectedTool = selectedNode ? toolById.get(selectedNode.toolId) : undefined;
  const removeGraphEdge = (edge: GeneratedWorkflowBuilderController["graphDraft"]["edges"][number]) => {
    builder.setInputBinding(edge.to.nodeId, edge.to.port, "");
  };
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Workflow strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
          <div className="min-w-0">
            <div className="text-sm font-medium text-slate-900">规则图</div>
            <div className="text-[11px] text-slate-500">{nodes.length} nodes / {edges.length} edges</div>
          </div>
        </div>
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-[240px_minmax(0,1fr)_260px]">
        <div className="rounded-md border border-slate-100 bg-slate-50 px-2 py-2">
          <div className="mb-2 px-1 text-[11px] font-semibold text-slate-400">工具库</div>
          <div className="grid gap-1.5">
            {tools.map((tool) => (
              <RulePaletteCard
                key={tool.id}
                tool={tool}
                onClick={() => builder.addStep(tool.id)}
              />
            ))}
          </div>
        </div>

        <div className="min-h-[190px] rounded-md border border-slate-100 bg-slate-50 px-3 py-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="text-xs font-medium text-slate-700">画布</div>
            <div className="font-mono text-[11px] text-slate-400">{edges.length} edges</div>
          </div>
          <GeneratedWorkflowGraphCanvas
            edges={edges}
            nodes={nodes}
            onSelectNode={setSelectedNodeId}
            selectedNodeId={selectedNode?.id || ""}
            tools={tools}
          />
          <div className="mt-3 grid gap-1.5">
            {edges.length === 0 ? (
              <div className="rounded-md bg-white px-3 py-2 text-xs text-slate-500">节点之间还没有显式连线。</div>
            ) : edges.map((edge) => (
              <div key={edge.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-md bg-white px-3 py-2">
                <div className="min-w-0">
                  <div className="font-mono text-xs text-slate-700">
                    <span className="break-all">{edge.from.nodeId}.{edge.from.port}</span>
                    <span className="px-2 text-slate-400">-&gt;</span>
                    <span className="break-all">{edge.to.nodeId}.{edge.to.port}</span>
                  </div>
                  <EdgeAuditBadge audit={edge.audit} />
                </div>
                <Button
                  type="button"
                  variant="outline"
                  className="h-7 bg-white px-2 text-[11px]"
                  onClick={() => removeGraphEdge(edge)}
                  aria-label="删除连线"
                >
                  <Trash2 strokeWidth={1.5} className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-md border border-slate-100 bg-slate-50 px-3 py-3">
          <div className="mb-2 text-[11px] font-semibold uppercase text-slate-400">Inspector</div>
          {selectedNode ? (
            <div className="grid gap-2">
              <div>
                <div className="flex min-w-0 items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate font-mono text-xs text-slate-800">{selectedNode.id}</div>
                    <div className="truncate text-[11px] text-slate-500">{selectedTool?.name || selectedNode.toolId}</div>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    className="h-7 shrink-0 bg-white px-2 text-[11px]"
                    disabled={nodes.length <= 1}
                    onClick={() => {
                      builder.removeStep(selectedNode.id);
                      setSelectedNodeId("");
                    }}
                    aria-label="删除节点"
                  >
                    <Trash2 strokeWidth={1.5} className="mr-1 h-3.5 w-3.5" />
                    删除节点
                  </Button>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="rounded bg-white px-2 py-1">
                  <div className="text-sm font-semibold text-slate-800">{readRuleInputs(selectedTool).length}</div>
                  <div className="text-[11px] text-slate-400">inputs</div>
                </div>
                <div className="rounded bg-white px-2 py-1">
                  <div className="text-sm font-semibold text-slate-800">{readRuleOutputs(selectedTool).length}</div>
                  <div className="text-[11px] text-slate-400">outputs</div>
                </div>
                <div className="rounded bg-white px-2 py-1">
                  <div className="text-sm font-semibold text-slate-800">{readRuleParams(selectedTool).length}</div>
                  <div className="text-[11px] text-slate-400">params</div>
                </div>
              </div>
              <GeneratedWorkflowNodeSettings
                nodeId={selectedNode.id}
                toolId={selectedNode.toolId}
                tools={tools}
                onStepIdChange={(nextId: string) => builder.setStepId(selectedNode.id, nextId)}
                onStepToolChange={(toolId: string) => builder.setStepTool(selectedNode.id, toolId)}
              />
              <GeneratedWorkflowRuleSpecPanel tool={selectedTool} />
              <StepParamsEditor
                params={selectedNode.params || {}}
                paramSpecs={readRuleParams(selectedTool)}
                onChange={(paramName, value) => builder.setStepParam(selectedNode.id, paramName, value)}
              />
              <GeneratedWorkflowRuntimeEditor
                runtime={selectedNode.runtime}
                tool={selectedTool}
                onChange={(runtime) => builder.setStepRuntime(selectedNode.id, runtime)}
              />
              <GeneratedWorkflowSnakefilePreview node={selectedNode} tool={selectedTool} />
              <GeneratedWorkflowPortBindingsEditor
                edges={edges}
                inputCount={inputCount}
                node={selectedNode}
                outputCandidates={outputCandidates}
                tool={selectedTool}
                onBind={(inputName, binding) => builder.setInputBinding(selectedNode.id, inputName, binding)}
              />
            </div>
          ) : (
            <div className="rounded-md bg-white px-3 py-2 text-xs text-slate-500">未选择节点。</div>
          )}
        </div>
      </div>
      <div className="mt-3">
        <GeneratedWorkflowGraphSnakefilePreview draft={builder.graphDraft} tools={tools} />
      </div>
    </div>
  );
}

function RulePaletteCard({ onClick, tool }: { onClick: () => void; tool: AddedTool }) {
  const action = ruleActionLabelForTool(tool);
  const ports = rulePortsLabelForTool(tool);
  const environment = ruleEnvironmentLabelForTool(tool);
  return (
    <Button
      type="button"
      variant="outline"
      className="h-auto w-full items-start justify-start gap-2 bg-white px-2 py-2 text-left text-xs"
      onClick={onClick}
    >
      <Plus strokeWidth={1.5} className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500" />
      <span className="grid min-w-0 flex-1 gap-1">
        <span className="flex min-w-0 items-center justify-between gap-2">
          <span className="min-w-0 truncate font-medium text-slate-800">{tool.name}</span>
          <span className="shrink-0 rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] leading-none text-slate-500">
            RuleSpec 节点
          </span>
        </span>
        <span className="truncate font-mono text-[11px] leading-4 text-slate-500" title={action}>
          {action}
        </span>
        <span className="flex min-w-0 flex-wrap gap-1">
          <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-700">{ports}</span>
          <span className="max-w-full truncate rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700" title={environment}>
            {environment}
          </span>
        </span>
      </span>
    </Button>
  );
}

function EdgeAuditBadge({ audit }: { audit: GeneratedWorkflowBuilderController["graphDraft"]["edges"][number]["audit"] }) {
  if (!audit) return null;
  return (
    <div className="mt-1 truncate text-[10px] text-slate-500">
      {audit.source === "auto" ? "自动推荐" : "手动连接"} · {audit.reason}
    </div>
  );
}

function OutputExposureEditor({
  builder,
  outputCandidates,
}: {
  builder: GeneratedWorkflowBuilderController;
  outputCandidates: GeneratedWorkflowOutputCandidate[];
}) {
  const exposableCandidates = outputCandidates.filter((candidate) => candidate.port.temp !== true);
  const first = exposableCandidates[0];
  return (
    <div className="rounded-lg border border-slate-200 px-3 py-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-medium text-slate-900">暴露输出</div>
        <Button
          type="button"
          variant="outline"
          className="h-8 bg-white px-2.5 text-xs"
          disabled={!first}
          onClick={() => first && builder.addExposedOutput({ fromStep: first.stepId, output: first.output, as: first.output })}
        >
          <Plus strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
          添加输出
        </Button>
      </div>
      <div className="mt-3 grid gap-2">
        {builder.draft.exposeOutputs.length === 0 ? (
          <div className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500">默认暴露拓扑末端步骤输出。</div>
        ) : exposableCandidates.length === 0 ? (
          <div className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500">没有可暴露输出。</div>
        ) : builder.draft.exposeOutputs.map((output, index) => (
          <div key={`${output.fromStep}-${output.output}-${index}`} className="grid gap-2 md:grid-cols-[minmax(0,1fr)_160px_auto]">
            <Select
              value={`${output.fromStep}.${output.output}`}
              onValueChange={(value) => {
                const candidate = exposableCandidates.find((item) => item.value === value);
                if (candidate) builder.setExposedOutput(index, { ...output, fromStep: candidate.stepId, output: candidate.output });
              }}
            >
              <SelectTrigger className="h-8 bg-white text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {exposableCandidates.map((candidate) => (
                  <SelectItem key={candidate.value} value={candidate.value}>{candidate.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              value={output.as}
              onChange={(event) => builder.setExposedOutput(index, { ...output, as: event.target.value })}
              className="h-8 font-mono text-xs"
              placeholder="alias"
            />
            <Button type="button" variant="outline" className="h-8 bg-white px-2" onClick={() => builder.removeExposedOutput(index)}>
              <Trash2 strokeWidth={1.5} className="h-3.5 w-3.5" />
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}

function GeneratedResourceBindings({
  builder,
  availableDatabases,
}: {
  builder: GeneratedWorkflowBuilderController;
  availableDatabases: DatabaseItem[];
}) {
  if (builder.resourceEntries.length === 0) return null;
  return (
    <div className="rounded-lg border border-slate-200 px-3 py-3">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-900">
        <Database strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
        数据库资源
      </div>
      <div className="grid gap-2">
        {builder.resourceEntries.map(([key, spec]) => {
          const candidates = availableDatabases.filter((database) => databaseMatchesWorkflowResource(database, spec));
          const value = builder.selectedResourceDatabaseIds[key] || "__none__";
          return (
            <div key={key} className="grid gap-2 rounded-md bg-slate-50 px-3 py-2 md:grid-cols-[minmax(0,1fr)_240px]">
              <div className="min-w-0">
                <div className="truncate font-mono text-xs text-slate-700">{key}</div>
                <div className="text-[11px] text-slate-500">{spec.required ? "必选" : "可选"} · {candidates.length} 个候选</div>
              </div>
              <Select value={value} onValueChange={(next) => builder.setResourceBinding(key, next === "__none__" ? "" : next)}>
                <SelectTrigger className="h-8 bg-white text-xs">
                  <SelectValue placeholder="选择数据库" />
                </SelectTrigger>
                <SelectContent>
                  {!spec.required ? <SelectItem value="__none__">不绑定</SelectItem> : null}
                  {candidates.map((database) => (
                    <SelectItem key={database.id} value={database.id}>{database.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function buildOutputCandidates(
  steps: GeneratedWorkflowBuilderController["draft"]["steps"],
  tools: AddedTool[]
): GeneratedWorkflowOutputCandidate[] {
  return steps.flatMap((step) => {
    const tool = tools.find((item) => item.id === step.toolId);
    return readRuleOutputs(tool).map((output) => ({
      value: `${step.id}.${output.name}`,
      label: `${step.id}.${output.name} · ${describePortSpec(output)}`,
      stepId: step.id,
      output: output.name,
      port: output,
    }));
  });
}

function ruleActionLabelForTool(tool: AddedTool) {
  const template = ruleTemplateForPaletteTool(tool);
  const wrapper = stringValue(template.wrapper);
  if (wrapper) return `wrapper: ${wrapper}`;
  const script = stringValue(template.script);
  if (script) return `script: ${script}`;
  const command = stringValue(template.commandTemplate);
  if (command) return command;
  if (readRuleInputs(tool).length > 0 || readRuleOutputs(tool).length > 0) return "端口契约待补 action";
  return "RuleSpec 待补全";
}

function rulePortsLabelForTool(tool: AddedTool) {
  return `${readRuleInputs(tool).length} in / ${readRuleOutputs(tool).length} out / ${readRuleParams(tool).length} params`;
}

function ruleEnvironmentLabelForTool(tool: AddedTool) {
  const template = ruleTemplateForPaletteTool(tool);
  const environment = recordValue(template.environment);
  const conda = recordValue(environment.conda);
  const dependencies = stringArray(conda.dependencies);
  const channels = stringArray(conda.channels);
  const container = stringValue(environment.container) || stringValue(recordValue(environment.container).url) || stringValue(recordValue(environment.container).image);
  if (dependencies.length > 0) return `运行环境 ${dependencies.length} deps`;
  if (channels.length > 0) return `运行环境 ${channels.length} channels`;
  if (container) return "运行环境 container";
  if (tool.selectedPackageSpec || tool.packageSpec) return "运行环境 package lock";
  return "运行环境待声明";
}

function ruleTemplateForPaletteTool(tool: AddedTool): Record<string, unknown> {
  const manifest = (tool.ruleTemplate || {}) as Record<string, unknown>;
  const draft = (tool.ruleSpecDraft?.ruleTemplate || {}) as Record<string, unknown>;
  if (hasPaletteRuleAction(manifest)) return manifest;
  if (hasPaletteRuleAction(draft)) return draft;
  return Object.keys(manifest).length > 0 ? manifest : draft;
}

function hasPaletteRuleAction(template: Record<string, unknown>) {
  return Boolean(stringValue(template.commandTemplate) || stringValue(template.wrapper) || stringValue(template.script));
}

function recordValue(raw: unknown): Record<string, unknown> {
  return raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
}

function stringArray(raw: unknown) {
  return Array.isArray(raw) ? raw.map(stringValue).filter(Boolean) : [];
}

function stringValue(raw: unknown) {
  return typeof raw === "string" ? raw.trim() : "";
}
