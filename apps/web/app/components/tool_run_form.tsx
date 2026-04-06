"use client";

import { useEffect, useMemo, useState } from "react";

type ToolRunFormProps = {
  descriptor: Record<string, unknown> | null;
  toolId: string;
  onRun: (params: Record<string, unknown>) => Promise<void>;
  busy?: boolean;
};

type DescriptorInput = {
  name: string;
  label: string;
  description: string;
  required: boolean;
};

type DescriptorParam = {
  name: string;
  label: string;
  description: string;
  type: string;
  defaultValue: unknown;
  choices: unknown[];
};

type DescriptorDatabase = {
  id: string;
  paramName: string;
  label: string;
  description: string;
  required: boolean;
  defaultValue: unknown;
};

type DescriptorPreset = {
  id: string;
  label: string;
  notes: string;
  params: Record<string, unknown>;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function asText(value: unknown, fallback = ""): string {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed || fallback;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return fallback;
}

function parseInputs(descriptor: Record<string, unknown> | null): DescriptorInput[] {
  const raw = descriptor?.inputs;
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw
    .map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const name = asText(item.name);
      if (!name) {
        return null;
      }
      return {
        name,
        label: asText(item.label, name),
        description: asText(item.description),
        required: item.required !== false,
      };
    })
    .filter((item): item is DescriptorInput => !!item);
}

function parseParams(descriptor: Record<string, unknown> | null): DescriptorParam[] {
  const raw = descriptor?.parameters;
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw
    .map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const name = asText(item.name);
      if (!name) {
        return null;
      }
      return {
        name,
        label: asText(item.label, name),
        description: asText(item.description),
        type: asText(item.type, "string").toLowerCase(),
        defaultValue: item.default,
        choices: Array.isArray(item.choices) ? item.choices : [],
      };
    })
    .filter((item): item is DescriptorParam => !!item);
}

function parseDatabases(descriptor: Record<string, unknown> | null): DescriptorDatabase[] {
  const raw = descriptor?.databases;
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw
    .map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const id = asText(item.id);
      const paramName = asText(item.param_name || item.name || id);
      if (!paramName) {
        return null;
      }
      return {
        id,
        paramName,
        label: asText(item.label, paramName),
        description: asText(item.description),
        required: Boolean(item.required),
        defaultValue: item.default,
      };
    })
    .filter((item): item is DescriptorDatabase => !!item);
}

function parsePresets(descriptor: Record<string, unknown> | null): DescriptorPreset[] {
  const usage = descriptor?.usage;
  if (!isRecord(usage) || !Array.isArray(usage.presets)) {
    return [];
  }
  return usage.presets
    .map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const id = asText(item.id);
      const label = asText(item.label, id || "preset");
      if (!id && !label) {
        return null;
      }
      return {
        id: id || label,
        label,
        notes: asText(item.notes),
        params: isRecord(item.params) ? item.params : {},
      };
    })
    .filter((item): item is DescriptorPreset => !!item);
}

function stringifyDefault(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (typeof value === "number") {
    return String(value);
  }
  if (typeof value === "string") {
    return value;
  }
  return "";
}

function coerceParamValue(param: DescriptorParam, raw: string): unknown {
  const normalized = raw.trim();
  if (normalized === "") {
    return undefined;
  }
  if (param.type === "int" || param.type === "integer") {
    const parsed = Number.parseInt(normalized, 10);
    return Number.isFinite(parsed) ? parsed : normalized;
  }
  if (param.type === "float" || param.type === "number") {
    const parsed = Number.parseFloat(normalized);
    return Number.isFinite(parsed) ? parsed : normalized;
  }
  if (param.type === "bool" || param.type === "boolean") {
    if (normalized === "true") {
      return true;
    }
    if (normalized === "false") {
      return false;
    }
    return normalized;
  }
  return normalized;
}

export function ToolRunForm({ descriptor, toolId, onRun, busy = false }: ToolRunFormProps) {
  const inputs = useMemo(() => parseInputs(descriptor), [descriptor]);
  const params = useMemo(() => parseParams(descriptor), [descriptor]);
  const databases = useMemo(() => parseDatabases(descriptor), [descriptor]);
  const presets = useMemo(() => parsePresets(descriptor), [descriptor]);

  const [sampleName, setSampleName] = useState<string>("web_demo_sample");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [selectedPresetId, setSelectedPresetId] = useState<string>("");
  const [presetNotes, setPresetNotes] = useState<string>("");

  useEffect(() => {
    const next: Record<string, string> = {};
    for (const input of inputs) {
      next[input.name] = "";
    }
    for (const param of params) {
      next[param.name] = stringifyDefault(param.defaultValue);
    }
    for (const db of databases) {
      next[db.paramName] = stringifyDefault(db.defaultValue);
    }
    setFields(next);
    setSelectedPresetId("");
    setPresetNotes("");
    setSampleName("web_demo_sample");
  }, [toolId, inputs, params, databases]);

  const onChangeField = (name: string, value: string) => {
    setFields((prev) => ({ ...prev, [name]: value }));
  };

  const applyPreset = (presetId: string) => {
    setSelectedPresetId(presetId);
    const preset = presets.find((item) => item.id === presetId);
    if (!preset) {
      setPresetNotes("");
      return;
    }
    setPresetNotes(preset.notes);
    setFields((prev) => {
      const merged = { ...prev };
      for (const param of params) {
        if (Object.prototype.hasOwnProperty.call(preset.params, param.name)) {
          merged[param.name] = stringifyDefault(preset.params[param.name]);
        }
      }
      return merged;
    });
  };

  const run = async () => {
    const payload: Record<string, unknown> = {};
    if (sampleName.trim()) {
      payload.__sample_name = sampleName.trim();
    }

    for (const input of inputs) {
      const value = asText(fields[input.name]).trim();
      if (value) {
        payload[input.name] = value;
      }
    }

    for (const param of params) {
      const raw = asText(fields[param.name]);
      const value = coerceParamValue(param, raw);
      if (value !== undefined) {
        payload[param.name] = value;
      }
    }

    for (const db of databases) {
      const value = asText(fields[db.paramName]).trim();
      if (value) {
        payload[db.paramName] = value;
      }
    }

    await onRun(payload);
  };

  const clear = () => {
    const next: Record<string, string> = {};
    for (const key of Object.keys(fields)) {
      next[key] = "";
    }
    setFields(next);
    setSampleName("");
    setSelectedPresetId("");
    setPresetNotes("");
  };

  return (
    <div className="tool-run-form">
      <div className="form-section">
        <h3>样本</h3>
        <label className="field-label" htmlFor="sample-name">
          Sample Name
        </label>
        <input
          id="sample-name"
          className="input-control"
          value={sampleName}
          onChange={(event) => setSampleName(event.target.value)}
          placeholder="optional"
        />
      </div>

      <div className="form-section">
        <h3>输入</h3>
        {inputs.length === 0 ? <p className="muted">No input files required</p> : null}
        {inputs.map((input) => (
          <div className="field-block" key={input.name}>
            <label className="field-label" htmlFor={`input-${input.name}`}>
              {input.label}
              {input.required ? <span className="required-mark"> *</span> : null}
            </label>
            <input
              id={`input-${input.name}`}
              className="input-control"
              value={asText(fields[input.name])}
              onChange={(event) => onChangeField(input.name, event.target.value)}
              placeholder={input.description || "local/remote path"}
            />
            {input.description ? <div className="field-help">{input.description}</div> : null}
          </div>
        ))}
      </div>

      <div className="form-section">
        <h3>参数</h3>
        {presets.length > 0 ? (
          <div className="preset-row">
            <select
              className="ui-select"
              value={selectedPresetId}
              onChange={(event) => applyPreset(event.target.value)}
            >
              <option value="">选择预设</option>
              {presets.map((preset) => (
                <option value={preset.id} key={preset.id}>
                  {preset.label}
                </option>
              ))}
            </select>
            {presetNotes ? <span className="muted">{presetNotes}</span> : null}
          </div>
        ) : null}
        {params.length === 0 ? <p className="muted">No parameters to configure</p> : null}
        {params.map((param) => (
          <div className="field-block" key={param.name}>
            <label className="field-label" htmlFor={`param-${param.name}`}>
              {param.label}
            </label>
            {param.type === "bool" || param.type === "boolean" ? (
              <select
                id={`param-${param.name}`}
                className="ui-select"
                value={asText(fields[param.name])}
                onChange={(event) => onChangeField(param.name, event.target.value)}
              >
                <option value="">(unset)</option>
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            ) : Array.isArray(param.choices) && param.choices.length > 0 ? (
              <select
                id={`param-${param.name}`}
                className="ui-select"
                value={asText(fields[param.name])}
                onChange={(event) => onChangeField(param.name, event.target.value)}
              >
                <option value="">(unset)</option>
                {param.choices.map((choice) => {
                  const value = asText(choice);
                  return (
                    <option key={`${param.name}-${value}`} value={value}>
                      {value}
                    </option>
                  );
                })}
              </select>
            ) : (
              <input
                id={`param-${param.name}`}
                className="input-control"
                value={asText(fields[param.name])}
                onChange={(event) => onChangeField(param.name, event.target.value)}
                placeholder={param.description || param.type}
              />
            )}
            {param.description ? <div className="field-help">{param.description}</div> : null}
          </div>
        ))}
      </div>

      <div className="form-section">
        <h3>数据库</h3>
        {databases.length === 0 ? <p className="muted">No required databases</p> : null}
        {databases.map((db) => (
          <div className="field-block" key={`${db.id}-${db.paramName}`}>
            <label className="field-label" htmlFor={`db-${db.paramName}`}>
              {db.label || db.paramName}
              {db.required ? <span className="required-mark"> *</span> : null}
            </label>
            <input
              id={`db-${db.paramName}`}
              className="input-control"
              value={asText(fields[db.paramName])}
              onChange={(event) => onChangeField(db.paramName, event.target.value)}
              placeholder={db.description || "database path"}
            />
            {db.description ? <div className="field-help">{db.description}</div> : null}
          </div>
        ))}
      </div>

      <div className="form-actions">
        <button id="run-btn" className="ui-button ui-button--primary" onClick={() => void run()} disabled={busy}>
          {busy ? "提交中..." : "▶ 运行工具"}
        </button>
        <button id="clear-btn" className="ui-button ui-button--secondary" onClick={clear} disabled={busy}>
          清空
        </button>
      </div>
    </div>
  );
}
