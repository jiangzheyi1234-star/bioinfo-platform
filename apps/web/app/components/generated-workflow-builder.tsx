"use client";

import { useMemo, useState } from "react";
import { AlertCircle, Database, Plus, Trash2, Workflow } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

import type { DatabaseItem } from "./database-page-model";
import type { AddedTool } from "./tools-page-model";
import {
  describePortSpec,
  portCompatibilityScore,
  portsCompatible,
  readRuleInputs,
  readRuleOutputs,
  readRuleParams,
  type GeneratedWorkflowInputBinding,
  type RuleInputSpec,
  type RuleOutputSpec,
} from "./generated-workflow-model";
import {
  autoEdgeAudit,
  explainPortRecommendation,
  isAutoBindablePortRecommendation,
  type RulePortRecommendation,
} from "./generated-workflow-recommendation-contract";
import { RuleGraphNodeCard } from "./generated-workflow-graph-node-card";
import { GeneratedWorkflowNodeSettings } from "./generated-workflow-node-settings";
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
  outputCandidates: OutputCandidate[];
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
          <div className="mb-2 px-1 text-[11px] font-semibold uppercase text-slate-400">工具 Palette · 规则节点库</div>
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
          <div className="grid gap-2 md:grid-cols-2">
            {nodes.length === 0 ? (
              <div className="rounded-md bg-white px-3 py-2 text-xs text-slate-500">还没有规则节点。</div>
            ) : nodes.map((node) => {
              const tool = toolById.get(node.toolId);
              const selected = selectedNode?.id === node.id;
              return (
                <RuleGraphNodeCard
                  edges={edges}
                  key={node.id}
                  node={node}
                  onSelect={() => setSelectedNodeId(node.id)}
                  selected={selected}
                  tool={tool}
                />
              );
            })}
          </div>
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
              <PortBindingsEditor
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

function PortBindingsEditor({
  edges,
  inputCount,
  node,
  onBind,
  outputCandidates,
  tool,
}: {
  edges: GeneratedWorkflowBuilderController["graphDraft"]["edges"];
  inputCount: number;
  node: GeneratedWorkflowBuilderController["graphDraft"]["nodes"][number];
  onBind: (inputName: string, binding: GeneratedWorkflowInputBinding) => void;
  outputCandidates: OutputCandidate[];
  tool: AddedTool | undefined;
}) {
  const inputs = readRuleInputs(tool);
  if (inputs.length === 0) {
    return <div className="rounded-md bg-white px-3 py-2 text-xs text-slate-500">此节点没有输入端口。</div>;
  }
  return (
    <div className="grid gap-2">
      <div className="text-[11px] font-semibold uppercase text-slate-400">端口绑定</div>
      {inputs.map((input) => {
        const edgeForInput = edges.find((edge) => edge.to.nodeId === node.id && edge.to.port === input.name);
        const binding = edgeForInput
          ? { fromStep: edgeForInput.from.nodeId, output: edgeForInput.from.port }
          : node.inputs[input.name];
        const candidates = outputCandidates
          .filter((candidate) => candidate.stepId !== node.id)
          .map((candidate) => {
            const recommendation = explainPortRecommendation(input, candidate.port);
            return {
              ...candidate,
              compatible: portsCompatible(input, candidate.port),
              compatibilityReason: recommendation.reason,
              compatibilityScore: portCompatibilityScore(input, candidate.port),
              recommendation,
            };
          });
        return (
          <PortBindingRow
            key={input.name}
            binding={binding}
            input={input}
            inputCount={inputCount}
            outputCandidates={candidates}
            onChange={(nextBinding) => onBind(input.name, nextBinding)}
          />
        );
      })}
    </div>
  );
}

type OutputCandidate = {
  value: string;
  label: string;
  stepId: string;
  output: string;
  port: RuleOutputSpec;
  compatible?: boolean;
  compatibilityReason?: string;
  compatibilityScore?: number | null;
  recommendation?: RulePortRecommendation;
};

function PortBindingRow({
  binding,
  input,
  inputCount,
  outputCandidates,
  onChange,
}: {
  binding: GeneratedWorkflowInputBinding | undefined;
  input: RuleInputSpec;
  inputCount: number;
  outputCandidates: OutputCandidate[];
  onChange: (binding: GeneratedWorkflowInputBinding) => void;
}) {
  const type = bindingKind(binding);
  const required = input.required !== false;
  const compatibleOutputCandidates = rankOutputCandidates(outputCandidates.filter((candidate) => candidate.compatible !== false));
  const recommendedOutputCandidates = compatibleOutputCandidates.filter(isRecommendedOutputCandidate);
  const recommended = recommendedOutputCandidates[0];
  const manualOnlyCandidate = compatibleOutputCandidates.find((candidate) => candidate.recommendation?.decision === "ambiguous");
  const hasBinding = Boolean(binding);
  return (
    <div className="grid gap-2 rounded-md bg-white px-2 py-2">
      <div className="flex min-w-0 items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-mono text-[11px] text-slate-700">{input.name}</div>
          <div className="truncate text-[11px] text-slate-400">{describePortSpec(input)}</div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <div className={cn("text-[11px]", required ? "text-amber-600" : "text-slate-400")}>
            {required ? "required" : "optional"}
          </div>
          {hasBinding ? (
            <Button type="button" variant="outline" className="h-7 bg-white px-2 text-[11px]" onClick={() => onChange("")}>
              解绑
            </Button>
          ) : recommended ? (
            <Button
              type="button"
              variant="outline"
              className="h-7 bg-white px-2 text-[11px]"
              onClick={() =>
                onChange({ fromStep: recommended.stepId, output: recommended.output, audit: autoEdgeAudit(recommended.recommendation) })
              }
            >
              应用推荐
            </Button>
          ) : null}
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-[120px_minmax(0,1fr)]">
        <Select value={type} onValueChange={(nextType) => onChange(defaultBinding(nextType, compatibleOutputCandidates))}>
          <SelectTrigger className="h-8 bg-white text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="fromUpload">上传文件</SelectItem>
            <SelectItem value="fromInput">输入 role</SelectItem>
            <SelectItem value="fromStep">上游输出</SelectItem>
            <SelectItem value="path">直接路径</SelectItem>
          </SelectContent>
        </Select>
        <PortBindingValueEditor
          binding={binding}
          inputCount={inputCount}
          outputCandidates={outputCandidates}
          type={type}
          onChange={onChange}
        />
      </div>
      {recommended?.compatibilityReason ? (
        <div className="truncate text-[11px] text-slate-500">推荐原因: {recommended.compatibilityReason}</div>
      ) : null}
      {recommended?.recommendation ? (
        <div className="truncate text-[11px] text-slate-500">
          推荐证据: {recommended.recommendation.evidence.join(" · ")} · confidence{" "}
          {formatRecommendationConfidence(recommended.recommendation.confidence)}
        </div>
      ) : null}
      {!recommended && manualOnlyCandidate?.recommendation ? (
        <div className="truncate text-[11px] text-slate-500">
          手动连接提示: {manualOnlyCandidate.recommendation.evidence.join(" · ")}
        </div>
      ) : null}
    </div>
  );
}

function isRecommendedOutputCandidate(candidate: OutputCandidate): candidate is OutputCandidate & { recommendation: RulePortRecommendation } {
  return candidate.recommendation?.decision === "recommended" && isAutoBindablePortRecommendation(candidate.recommendation);
}

function EdgeAuditBadge({ audit }: { audit: GeneratedWorkflowBuilderController["graphDraft"]["edges"][number]["audit"] }) {
  if (!audit) return null;
  return (
    <div className="mt-1 truncate text-[10px] text-slate-500">
      {audit.source === "auto" ? "自动推荐" : "手动连接"} · {audit.reason}
    </div>
  );
}

function PortBindingValueEditor({
  binding,
  inputCount,
  outputCandidates,
  type,
  onChange,
}: {
  binding: GeneratedWorkflowInputBinding | undefined;
  inputCount: number;
  outputCandidates: OutputCandidate[];
  type: string;
  onChange: (binding: GeneratedWorkflowInputBinding) => void;
}) {
  if (type === "fromStep") {
    const value = typeof binding === "object" && binding && "fromStep" in binding ? `${binding.fromStep}.${binding.output}` : "__none__";
    const rankedCandidates = rankOutputCandidates(outputCandidates);
    const compatibleCandidates = rankedCandidates.filter((candidate) => candidate.compatible !== false);
    const recommended = compatibleCandidates.find((candidate) => candidate.recommendation?.decision === "recommended");
    return (
      <Select value={value} onValueChange={(next) => {
        if (next === "__none__") {
          onChange("");
          return;
        }
        const candidate = outputCandidates.find((item) => item.value === next);
        if (candidate && candidate.compatible !== false) onChange({ fromStep: candidate.stepId, output: candidate.output });
      }}>
        <SelectTrigger className="h-8 bg-white text-xs">
          <SelectValue placeholder="选择上游输出" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__none__">未绑定</SelectItem>
          {rankedCandidates.map((candidate) => (
            <SelectItem key={candidate.value} value={candidate.value} disabled={candidate.compatible === false}>
              {candidate.compatible === false
                ? `${candidate.label}（${candidate.compatibilityReason || "不兼容"}）`
                : candidate.value === recommended?.value
                  ? `${candidate.label}（推荐） · ${candidate.compatibilityReason || "兼容"}`
                  : candidate.label}
            </SelectItem>
          ))}
          {compatibleCandidates.length === 0 && outputCandidates.length > 0 ? (
            <SelectItem value="__no_compatible__" disabled>
              无兼容上游输出
            </SelectItem>
          ) : null}
        </SelectContent>
      </Select>
    );
  }
  if (type === "fromInput") {
    const value = typeof binding === "object" && binding && "fromInput" in binding ? binding.fromInput : "input";
    return (
      <Select value={value} onValueChange={(role) => onChange({ fromInput: role })}>
        <SelectTrigger className="h-8 bg-white text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {Array.from({ length: Math.max(inputCount, 1) }).map((_, index) => {
            const role = index === 0 ? "input" : `input_${index + 1}`;
            return <SelectItem key={role} value={role}>{role}</SelectItem>;
          })}
        </SelectContent>
      </Select>
    );
  }
  if (type === "path") {
    return (
      <Input
        value={typeof binding === "string" ? binding : ""}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 bg-white font-mono text-xs"
        placeholder="/path/to/file"
      />
    );
  }
  const uploadIndex = typeof binding === "object" && binding && "fromUpload" in binding ? binding.fromUpload : 0;
  return (
    <Select value={String(uploadIndex)} onValueChange={(index) => onChange({ fromUpload: Number(index) })}>
      <SelectTrigger className="h-8 bg-white text-xs">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {Array.from({ length: Math.max(inputCount, 1) }).map((_, index) => (
          <SelectItem key={index} value={String(index)}>
            输入文件 {index + 1}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function OutputExposureEditor({
  builder,
  outputCandidates,
}: {
  builder: GeneratedWorkflowBuilderController;
  outputCandidates: OutputCandidate[];
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

function buildOutputCandidates(steps: GeneratedWorkflowBuilderController["draft"]["steps"], tools: AddedTool[]): OutputCandidate[] {
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
  return Boolean(stringValue(template.commandTemplate) || stringValue(template.wrapper));
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

function bindingKind(binding: GeneratedWorkflowInputBinding | undefined) {
  if (typeof binding === "string") return "path";
  if (binding && "fromStep" in binding) return "fromStep";
  if (binding && "fromInput" in binding) return "fromInput";
  return "fromUpload";
}

function defaultBinding(type: string, outputCandidates: OutputCandidate[]): GeneratedWorkflowInputBinding {
  if (type === "fromStep") {
    const first = outputCandidates[0];
    return first ? { fromStep: first.stepId, output: first.output } : "";
  }
  if (type === "fromInput") return { fromInput: "input" };
  if (type === "path") return "";
  return { fromUpload: 0 };
}

function rankOutputCandidates(candidates: OutputCandidate[]) {
  return [...candidates].sort((left, right) => (right.compatibilityScore ?? -1) - (left.compatibilityScore ?? -1));
}

function formatRecommendationConfidence(confidence: number) {
  return `${Math.round(confidence * 100)}%`;
}
