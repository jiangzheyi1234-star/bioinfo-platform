"use client";

import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import { CalendarClock, Loader2, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import type {
  WorkflowTrigger,
  WorkflowTriggerDefinitionCreateRequest,
  WorkflowTriggerDefinitionSource,
} from "./workflow-trigger-model";

type DefinitionFormState = {
  sourceType: WorkflowTriggerDefinitionSource;
  name: string;
  serverId: string;
  pipelineId: string;
  projectId: string;
  pipelineVersion: string;
  workflowRevisionId: string;
  uploadId: string;
  filename: string;
  paramKey: string;
  paramValue: string;
  cron: string;
  timezone: string;
  concurrencyPolicy: "Forbid" | "Allow";
  partitionUnit: "day" | "hour";
  enabled: boolean;
};

const DEFAULT_FORM: DefinitionFormState = {
  sourceType: "manual",
  name: "",
  serverId: "",
  pipelineId: "",
  projectId: "",
  pipelineVersion: "",
  workflowRevisionId: "",
  uploadId: "",
  filename: "",
  paramKey: "",
  paramValue: "",
  cron: "0 2 * * *",
  timezone: "UTC",
  concurrencyPolicy: "Forbid",
  partitionUnit: "day",
  enabled: true,
};

export function WorkflowTriggerDefinitionControl({
  creating,
  onCreate,
  serverIdHint = "",
}: {
  creating: boolean;
  onCreate: (request: WorkflowTriggerDefinitionCreateRequest) => Promise<WorkflowTrigger | null>;
  serverIdHint?: string;
}) {
  const [form, setForm] = useState<DefinitionFormState>(() => ({
    ...DEFAULT_FORM,
    serverId: serverIdHint,
  }));
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    if (!form.serverId && serverIdHint) {
      setForm((current) => ({ ...current, serverId: serverIdHint }));
    }
  }, [form.serverId, serverIdHint]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLocalError("");
    const request = buildCreateRequest(form);
    if (typeof request === "string") {
      setLocalError(request);
      return;
    }
    const created = await onCreate(request);
    if (created?.triggerId) {
      setForm((current) => ({
        ...DEFAULT_FORM,
        serverId: current.serverId,
        sourceType: current.sourceType,
      }));
    }
  }

  return (
    <section
      className="rounded-lg border border-slate-200 bg-white px-4 py-3"
      data-testid="workflow-trigger-definition-control"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <CalendarClock strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
            创建触发定义
          </div>
          <div className="mt-1 text-xs text-slate-500">Manual / cron / backfill definitions only</div>
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-600">
          <Checkbox
            checked={form.enabled}
            onCheckedChange={(checked) => setForm((current) => ({ ...current, enabled: checked === true }))}
          />
          enabled
        </label>
      </div>
      <form className="mt-3 grid gap-3" onSubmit={submit}>
        <div className="grid gap-3 md:grid-cols-[180px_minmax(0,1fr)_minmax(0,1fr)]">
          <Field label="source">
            <Select
              value={form.sourceType}
              onValueChange={(value) =>
                setForm((current) => ({ ...current, sourceType: value as WorkflowTriggerDefinitionSource }))
              }
            >
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="manual">manual</SelectItem>
                <SelectItem value="cron">cron</SelectItem>
                <SelectItem value="backfill">backfill</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label="name">
            <Input
              value={form.name}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              className="h-8 text-xs"
              placeholder="FASTQ daily summary"
            />
          </Field>
          <Field label="serverId">
            <Input
              value={form.serverId}
              onChange={(event) => setForm((current) => ({ ...current, serverId: event.target.value }))}
              className="h-8 font-mono text-xs"
              placeholder="srv_..."
            />
          </Field>
        </div>
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="pipelineId">
            <Input
              value={form.pipelineId}
              onChange={(event) => setForm((current) => ({ ...current, pipelineId: event.target.value }))}
              className="h-8 font-mono text-xs"
              placeholder="pipeline id"
            />
          </Field>
          <Field label="projectId">
            <Input
              value={form.projectId}
              onChange={(event) => setForm((current) => ({ ...current, projectId: event.target.value }))}
              className="h-8 font-mono text-xs"
              placeholder="optional"
            />
          </Field>
          <Field label="pipelineVersion">
            <Input
              value={form.pipelineVersion}
              onChange={(event) => setForm((current) => ({ ...current, pipelineVersion: event.target.value }))}
              className="h-8 font-mono text-xs"
              placeholder="optional"
            />
          </Field>
          <Field label="workflowRevisionId">
            <Input
              value={form.workflowRevisionId}
              onChange={(event) => setForm((current) => ({ ...current, workflowRevisionId: event.target.value }))}
              className="h-8 font-mono text-xs"
              placeholder="optional"
            />
          </Field>
        </div>
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="input uploadId">
            <Input
              value={form.uploadId}
              onChange={(event) => setForm((current) => ({ ...current, uploadId: event.target.value }))}
              className="h-8 font-mono text-xs"
              placeholder="optional"
            />
          </Field>
          <Field label="input filename">
            <Input
              value={form.filename}
              onChange={(event) => setForm((current) => ({ ...current, filename: event.target.value }))}
              className="h-8 text-xs"
              placeholder="reads.fastq"
            />
          </Field>
          <Field label="param key">
            <Input
              value={form.paramKey}
              onChange={(event) => setForm((current) => ({ ...current, paramKey: event.target.value }))}
              className="h-8 font-mono text-xs"
              placeholder="optional"
            />
          </Field>
          <Field label="param value">
            <Input
              value={form.paramValue}
              onChange={(event) => setForm((current) => ({ ...current, paramValue: event.target.value }))}
              className="h-8 text-xs"
              placeholder="optional"
            />
          </Field>
        </div>
        {form.sourceType === "cron" ? (
          <div className="grid gap-3 md:grid-cols-3">
            <Field label="cron">
              <Input
                value={form.cron}
                onChange={(event) => setForm((current) => ({ ...current, cron: event.target.value }))}
                className="h-8 font-mono text-xs"
                placeholder="0 2 * * *"
              />
            </Field>
            <Field label="timezone">
              <Input
                value={form.timezone}
                onChange={(event) => setForm((current) => ({ ...current, timezone: event.target.value }))}
                className="h-8 font-mono text-xs"
                placeholder="UTC"
              />
            </Field>
            <Field label="overlap">
              <Select
                value={form.concurrencyPolicy}
                onValueChange={(value) =>
                  setForm((current) => ({ ...current, concurrencyPolicy: value as "Forbid" | "Allow" }))
                }
              >
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="Forbid">Forbid</SelectItem>
                  <SelectItem value="Allow">Allow</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </div>
        ) : null}
        {form.sourceType === "backfill" ? (
          <div className="grid gap-3 md:grid-cols-3">
            <Field label="partition unit">
              <Select
                value={form.partitionUnit}
                onValueChange={(value) => setForm((current) => ({ ...current, partitionUnit: value as "day" | "hour" }))}
              >
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="day">day</SelectItem>
                  <SelectItem value="hour">hour</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </div>
        ) : null}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3">
          <div className="text-xs text-slate-500">
            Webhook and readiness definitions stay API-only until signed delivery and resource watcher setup have their own controls.
          </div>
          <Button type="submit" className="h-8 px-3 text-xs" disabled={creating}>
            {creating ? <Loader2 strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Plus strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />}
            创建 definition
          </Button>
        </div>
        {localError ? <p className="text-xs text-red-600">{localError}</p> : null}
      </form>
    </section>
  );
}

function Field({ children, label }: { children: ReactNode; label: string }) {
  return (
    <label className="block min-w-0">
      <span className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</span>
      {children}
    </label>
  );
}

function buildCreateRequest(form: DefinitionFormState): WorkflowTriggerDefinitionCreateRequest | string {
  const name = form.name.trim();
  const serverId = form.serverId.trim();
  const pipelineId = form.pipelineId.trim();
  if (!name) return "WORKFLOW_TRIGGER_NAME_REQUIRED";
  if (!serverId) return "WORKFLOW_TRIGGER_SERVER_ID_REQUIRED";
  if (!pipelineId) return "PIPELINE_ID_REQUIRED";

  const uploadId = form.uploadId.trim();
  const filename = form.filename.trim();
  if ((uploadId && !filename) || (!uploadId && filename)) {
    return "WORKFLOW_TRIGGER_INPUT_UPLOAD_AND_FILENAME_REQUIRED";
  }
  const paramKey = form.paramKey.trim();
  const paramValue = form.paramValue.trim();
  if ((paramKey && !paramValue) || (!paramKey && paramValue)) {
    return "WORKFLOW_TRIGGER_PARAM_KEY_AND_VALUE_REQUIRED";
  }

  const runSpec: WorkflowTriggerDefinitionCreateRequest["runSpec"] = { pipelineId };
  const projectId = form.projectId.trim();
  const pipelineVersion = form.pipelineVersion.trim();
  const workflowRevisionId = form.workflowRevisionId.trim();
  if (projectId) runSpec.projectId = projectId;
  if (pipelineVersion) runSpec.pipelineVersion = pipelineVersion;
  if (workflowRevisionId) runSpec.workflowRevisionId = workflowRevisionId;
  if (uploadId && filename) runSpec.inputs = [{ uploadId, filename }];
  if (paramKey && paramValue) runSpec.params = { [paramKey]: paramValue };

  if (form.sourceType === "manual") {
    return {
      name,
      sourceType: "manual",
      serverId,
      enabled: form.enabled,
      runSpec,
      triggerSpec: { mode: "manual" },
    };
  }
  if (form.sourceType === "cron") {
    const cron = form.cron.trim();
    const timezone = form.timezone.trim();
    if (!cron) return "CRON_TRIGGER_CRON_REQUIRED";
    if (!timezone) return "CRON_TRIGGER_TIMEZONE_REQUIRED";
    return {
      name,
      sourceType: "cron",
      serverId,
      enabled: form.enabled,
      runSpec,
      triggerSpec: {
        cron,
        timezone,
        concurrencyPolicy: form.concurrencyPolicy,
      },
    };
  }
  return {
    name,
    sourceType: "backfill",
    serverId,
    enabled: form.enabled,
    runSpec,
    triggerSpec: { partitionUnit: form.partitionUnit },
  };
}
