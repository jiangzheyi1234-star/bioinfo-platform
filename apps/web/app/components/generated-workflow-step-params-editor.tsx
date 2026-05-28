import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import type {
  GeneratedWorkflowParamValue,
  RuleParamSpec,
} from "./generated-workflow-model";

export function StepParamsEditor({
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
