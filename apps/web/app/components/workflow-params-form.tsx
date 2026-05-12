"use client";

import { useMemo } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import type { JsonSchema } from "./workflows-page-model";

export function WorkflowParamsForm({
  schema,
  values,
  onChange,
}: {
  schema: JsonSchema | undefined;
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}) {
  const properties = useMemo(() => {
    if (!schema || typeof schema !== "object") return [];
    const props = schema.properties || {};
    return Object.entries(props).map(([key, prop]) => ({
      key,
      prop: prop as {
        type?: string;
        enum?: unknown[];
        description?: string;
        default?: unknown;
        title?: string;
        minimum?: number;
        maximum?: number;
      },
      required: (schema.required || []).includes(key),
    }));
  }, [schema]);

  function updateValue(key: string, value: unknown) {
    onChange({ ...values, [key]: value });
  }

  return (
    <div className="grid gap-4 px-5 py-5 md:grid-cols-[160px_minmax(0,1fr)]">
      <div>
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-950 text-xs text-white">2</span>
          运行参数
        </div>
      </div>

      {properties.length === 0 ? (
        <div className="rounded-md border border-dashed border-slate-200 bg-slate-50 px-3 py-4 text-sm text-slate-500">
          此流程无需额外参数。
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
        {properties.map(({ key, prop, required }) => {
          const label = prop.title || key;
          const value = values[key];

          if (prop.enum && prop.enum.length > 0) {
            return (
              <div key={key} className="space-y-1.5">
                <Label className="text-xs">
                  {label}
                  {required ? <span className="ml-0.5 text-red-500">*</span> : null}
                </Label>
                <Select value={String(value ?? prop.default ?? "")} onValueChange={(v) => updateValue(key, v)}>
                  <SelectTrigger className="h-9 text-xs">
                    <SelectValue placeholder={`选择 ${label}`} />
                  </SelectTrigger>
                  <SelectContent>
                    {prop.enum.map((option) => (
                      <SelectItem key={String(option)} value={String(option)} className="text-xs">
                        {String(option)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {prop.description ? <p className="text-[11px] text-slate-500">{prop.description}</p> : null}
              </div>
            );
          }

          if (prop.type === "boolean") {
            return (
              <div key={key} className="flex items-start gap-2">
                <Checkbox
                  id={`param-${key}`}
                  checked={Boolean(value ?? prop.default ?? false)}
                  onCheckedChange={(checked) => updateValue(key, Boolean(checked))}
                />
                <div className="space-y-1 leading-none">
                  <Label htmlFor={`param-${key}`} className="text-xs">
                    {label}
                    {required ? <span className="ml-0.5 text-red-500">*</span> : null}
                  </Label>
                  {prop.description ? <p className="text-[11px] text-slate-500">{prop.description}</p> : null}
                </div>
              </div>
            );
          }

          if (prop.type === "number" || prop.type === "integer") {
            return (
              <div key={key} className="space-y-1.5">
                <Label htmlFor={`param-${key}`} className="text-xs">
                  {label}
                  {required ? <span className="ml-0.5 text-red-500">*</span> : null}
                </Label>
                <Input
                  id={`param-${key}`}
                  data-testid={`run-param-${key}`}
                  type="number"
                  min={prop.minimum}
                  max={prop.maximum}
                  value={value !== undefined ? String(value) : prop.default !== undefined ? String(prop.default) : ""}
                  onChange={(e) => {
                    const v = e.target.value;
                    updateValue(key, v === "" ? "" : prop.type === "integer" ? parseInt(v, 10) : parseFloat(v));
                  }}
                  className="h-9 text-xs"
                />
                {prop.description ? <p className="text-[11px] text-slate-500">{prop.description}</p> : null}
              </div>
            );
          }

          return (
            <div key={key} className="space-y-1.5">
              <Label htmlFor={`param-${key}`} className="text-xs">
                {label}
                {required ? <span className="ml-0.5 text-red-500">*</span> : null}
              </Label>
              <Input
                id={`param-${key}`}
                data-testid={`run-param-${key}`}
                type="text"
                value={String(value ?? prop.default ?? "")}
                onChange={(e) => updateValue(key, e.target.value)}
                className="h-9 text-xs"
              />
              {prop.description ? <p className="text-[11px] text-slate-500">{prop.description}</p> : null}
            </div>
          );
        })}
        </div>
      )}
    </div>
  );
}
