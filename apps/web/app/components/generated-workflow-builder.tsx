"use client";

import { AlertCircle, Database, Plus, Trash2, Workflow } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

import type { DatabaseItem } from "./database-page-model";
import type { AddedTool } from "./tools-page-model";
import {
  describePortSpec,
  portsCompatible,
  readRuleInputs,
  readRuleOutputs,
  readRuleParams,
  type GeneratedWorkflowInputBinding,
  type GeneratedWorkflowParamValue,
  type RuleInputSpec,
  type RuleOutputSpec,
  type RuleParamSpec,
} from "./generated-workflow-model";
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

      <div className="grid gap-3">
        {builder.draft.steps.map((step, index) => {
          const tool = tools.find((item) => item.id === step.toolId);
          return (
            <div key={step.id} className="rounded-lg border border-slate-200 bg-white px-3 py-3">
              <div className="grid gap-3 lg:grid-cols-[120px_minmax(0,1fr)_auto]">
                <div>
                  <div className="text-[11px] font-semibold uppercase text-slate-400">Step {index + 1}</div>
                  <Input
                    value={step.id}
                    onChange={(event) => builder.setStepId(step.id, event.target.value)}
                    className="mt-1 h-8 font-mono text-xs"
                    aria-label="step id"
                  />
                </div>
                <div>
                  <Label className="text-[11px] font-semibold uppercase text-slate-400">工具</Label>
                  <Select value={step.toolId} onValueChange={(toolId) => builder.setStepTool(step.id, toolId)}>
                    <SelectTrigger className="mt-1 h-8">
                      <SelectValue placeholder="选择工具" />
                    </SelectTrigger>
                    <SelectContent>
                      {tools.map((item) => (
                        <SelectItem key={item.id} value={item.id}>
                          {item.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  className="self-end h-8 bg-white px-2"
                  disabled={builder.draft.steps.length <= 1}
                  onClick={() => builder.removeStep(step.id)}
                  aria-label="删除步骤"
                >
                  <Trash2 strokeWidth={1.5} className="h-3.5 w-3.5" />
                </Button>
              </div>

              <div className="mt-3 grid gap-2">
                {readRuleInputs(tool).map((input) => (
                  <InputBindingRow
                    key={`${step.id}-${input.name}`}
                    binding={step.inputs[input.name]}
                    inputCount={inputCount}
                    input={input}
                    outputCandidates={outputCandidates
                      .filter((candidate) => candidate.stepId !== step.id)
                      .map((candidate) => ({ ...candidate, compatible: portsCompatible(input, candidate.port) }))}
                    onChange={(binding) => builder.setInputBinding(step.id, input.name, binding)}
                  />
                ))}
              </div>
              <StepParamsEditor
                params={step.params || {}}
                paramSpecs={readRuleParams(tool)}
                onChange={(paramName, value) => builder.setStepParam(step.id, paramName, value)}
              />
            </div>
          );
        })}
      </div>

      <OutputExposureEditor builder={builder} outputCandidates={outputCandidates} />
      <GeneratedResourceBindings builder={builder} availableDatabases={availableDatabases} />
    </div>
  );
}

function StepParamsEditor({
  params,
  paramSpecs,
  onChange,
}: {
  params: Record<string, GeneratedWorkflowParamValue>;
  paramSpecs: RuleParamSpec[];
  onChange: (paramName: string, value: GeneratedWorkflowParamValue) => void;
}) {
  if (paramSpecs.length === 0) return null;
  return (
    <div className="mt-3 rounded-md border border-slate-100 bg-white px-3 py-3">
      <div className="mb-2 text-[11px] font-semibold uppercase text-slate-400">运行参数</div>
      <div className="grid gap-2">
        {paramSpecs.map((param) => (
          <div key={param.name} className="grid gap-2 md:grid-cols-[140px_minmax(0,1fr)]">
            <Label className="min-w-0 pt-2 font-mono text-xs text-slate-600">{param.title || param.name}</Label>
            <ParamValueEditor
              param={param}
              value={params[param.name] ?? param.default ?? ""}
              onChange={(value) => onChange(param.name, value)}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function ParamValueEditor({
  param,
  value,
  onChange,
}: {
  param: RuleParamSpec;
  value: GeneratedWorkflowParamValue | "";
  onChange: (value: GeneratedWorkflowParamValue) => void;
}) {
  if (param.enum && param.enum.length > 0) {
    return (
      <Select value={String(value)} onValueChange={(next) => onChange(coerceParamValue(next, param))}>
        <SelectTrigger className="h-8 bg-white text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {param.enum.map((item) => (
            <SelectItem key={String(item)} value={String(item)}>{String(item)}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }
  if (param.type === "boolean") {
    return (
      <div className="flex h-8 items-center">
        <Checkbox checked={value === true} onCheckedChange={(checked) => onChange(checked === true)} />
      </div>
    );
  }
  if (param.type === "number" || param.type === "integer") {
    return (
      <Input
        type="number"
        value={String(value)}
        min={param.minimum}
        max={param.maximum}
        step={param.type === "integer" ? 1 : "any"}
        onChange={(event) => onChange(coerceParamValue(event.target.value, param))}
        className="h-8 bg-white font-mono text-xs"
      />
    );
  }
  return (
    <Input
      value={String(value)}
      onChange={(event) => onChange(event.target.value)}
      className="h-8 bg-white font-mono text-xs"
    />
  );
}

function coerceParamValue(value: string, param: RuleParamSpec): GeneratedWorkflowParamValue {
  if (param.type === "integer") {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : "";
  }
  if (param.type === "number") {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : "";
  }
  if (param.type === "boolean") {
    return value === "true";
  }
  return value;
}

type OutputCandidate = {
  value: string;
  label: string;
  stepId: string;
  output: string;
  port: RuleOutputSpec;
  compatible?: boolean;
};

function InputBindingRow({
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
  const compatibleOutputCandidates = outputCandidates.filter((candidate) => candidate.compatible !== false);
  return (
    <div className="grid gap-2 rounded-md bg-slate-50 px-3 py-2 md:grid-cols-[120px_150px_minmax(0,1fr)]">
      <div className="min-w-0">
        <div className="truncate font-mono text-xs text-slate-700">{input.name}</div>
        <div className={cn("text-[11px]", required ? "text-amber-600" : "text-slate-400")}>{required ? "required" : "optional"}</div>
        <div className="truncate text-[11px] text-slate-400">{describePortSpec(input)}</div>
      </div>
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
      <BindingValueEditor
        binding={binding}
        inputCount={inputCount}
        outputCandidates={outputCandidates}
        type={type}
        onChange={onChange}
      />
    </div>
  );
}

function BindingValueEditor({
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
    const compatibleCandidates = outputCandidates.filter((candidate) => candidate.compatible !== false);
    return (
      <Select value={value} onValueChange={(next) => {
        const candidate = outputCandidates.find((item) => item.value === next);
        if (candidate && candidate.compatible !== false) onChange({ fromStep: candidate.stepId, output: candidate.output });
      }}>
        <SelectTrigger className="h-8 bg-white text-xs">
          <SelectValue placeholder="选择上游输出" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__none__">未绑定</SelectItem>
          {outputCandidates.map((candidate) => (
            <SelectItem key={candidate.value} value={candidate.value} disabled={candidate.compatible === false}>
              {candidate.compatible === false ? `${candidate.label}（不兼容）` : candidate.label}
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
            upload {index + 1}
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
  const first = outputCandidates[0];
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
        ) : builder.draft.exposeOutputs.map((output, index) => (
          <div key={`${output.fromStep}-${output.output}-${index}`} className="grid gap-2 md:grid-cols-[minmax(0,1fr)_160px_auto]">
            <Select
              value={`${output.fromStep}.${output.output}`}
              onValueChange={(value) => {
                const candidate = outputCandidates.find((item) => item.value === value);
                if (candidate) builder.setExposedOutput(index, { ...output, fromStep: candidate.stepId, output: candidate.output });
              }}
            >
              <SelectTrigger className="h-8 bg-white text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {outputCandidates.map((candidate) => (
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
