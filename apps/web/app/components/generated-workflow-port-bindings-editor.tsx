"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

import type { AddedTool } from "./tools-page-model";
import {
  describePortSpec,
  portCompatibilityScore,
  portsCompatible,
  readRuleInputs,
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
import type { GeneratedWorkflowBuilderController } from "./use-generated-workflow-builder";

export type GeneratedWorkflowOutputCandidate = {
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

export function GeneratedWorkflowPortBindingsEditor({
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
  outputCandidates: GeneratedWorkflowOutputCandidate[];
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
  outputCandidates: GeneratedWorkflowOutputCandidate[];
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

function PortBindingValueEditor({
  binding,
  inputCount,
  outputCandidates,
  type,
  onChange,
}: {
  binding: GeneratedWorkflowInputBinding | undefined;
  inputCount: number;
  outputCandidates: GeneratedWorkflowOutputCandidate[];
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

function isRecommendedOutputCandidate(
  candidate: GeneratedWorkflowOutputCandidate
): candidate is GeneratedWorkflowOutputCandidate & { recommendation: RulePortRecommendation } {
  return candidate.recommendation?.decision === "recommended" && isAutoBindablePortRecommendation(candidate.recommendation);
}

function bindingKind(binding: GeneratedWorkflowInputBinding | undefined) {
  if (typeof binding === "string") return "path";
  if (binding && "fromStep" in binding) return "fromStep";
  if (binding && "fromInput" in binding) return "fromInput";
  return "fromUpload";
}

function defaultBinding(type: string, outputCandidates: GeneratedWorkflowOutputCandidate[]): GeneratedWorkflowInputBinding {
  if (type === "fromStep") {
    const first = outputCandidates[0];
    return first ? { fromStep: first.stepId, output: first.output } : "";
  }
  if (type === "fromInput") return { fromInput: "input" };
  if (type === "path") return "";
  return { fromUpload: 0 };
}

function rankOutputCandidates(candidates: GeneratedWorkflowOutputCandidate[]) {
  return [...candidates].sort((left, right) => (right.compatibilityScore ?? -1) - (left.compatibilityScore ?? -1));
}

function formatRecommendationConfidence(confidence: number) {
  return `${Math.round(confidence * 100)}%`;
}
