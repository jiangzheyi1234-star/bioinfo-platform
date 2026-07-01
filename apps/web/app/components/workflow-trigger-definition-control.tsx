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
  WorkflowTriggerWebhookProvider,
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
  webhookActions: string;
  webhookEventTypes: string;
  webhookProvider: WorkflowTriggerWebhookProvider;
  webhookSecretRef: string;
  webhookToleranceSeconds: string;
  watchAdapter: "local_path" | "database_registry";
  watchEnabled: boolean;
  watchPath: string;
  watchStabilitySeconds: string;
  resourceId: string;
  resourceUri: string;
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
  webhookActions: "",
  webhookEventTypes: "push",
  webhookProvider: "github",
  webhookSecretRef: "",
  webhookToleranceSeconds: "",
  watchAdapter: "local_path",
  watchEnabled: false,
  watchPath: "",
  watchStabilitySeconds: "",
  resourceId: "",
  resourceUri: "",
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
          <div className="mt-1 text-xs text-slate-500">Manual / cron / readiness / backfill definitions</div>
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
                setForm((current) => ({
                  ...current,
                  sourceType: value as WorkflowTriggerDefinitionSource,
                  watchAdapter: value === "database_ready" ? "database_registry" : "local_path",
                }))
              }
            >
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="manual">manual</SelectItem>
                <SelectItem value="cron">cron</SelectItem>
                <SelectItem value="webhook">webhook</SelectItem>
                <SelectItem value="dataset">dataset</SelectItem>
                <SelectItem value="file">file</SelectItem>
                <SelectItem value="database_ready">database-ready</SelectItem>
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
        {form.sourceType === "webhook" ? (
          <div className="grid gap-3 md:grid-cols-4">
            <Field label="provider">
              <Select
                value={form.webhookProvider}
                onValueChange={(value) =>
                  setForm((current) => ({ ...current, webhookProvider: value as WorkflowTriggerWebhookProvider }))
                }
              >
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="github">GitHub</SelectItem>
                  <SelectItem value="slack">Slack</SelectItem>
                  <SelectItem value="stripe">Stripe</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label="event types">
              <Input
                value={form.webhookEventTypes}
                onChange={(event) => setForm((current) => ({ ...current, webhookEventTypes: event.target.value }))}
                className="h-8 font-mono text-xs"
                placeholder={webhookEventTypesPlaceholder(form.webhookProvider)}
              />
            </Field>
            <Field label="actions">
              <Input
                value={form.webhookActions}
                onChange={(event) => setForm((current) => ({ ...current, webhookActions: event.target.value }))}
                className="h-8 font-mono text-xs"
                placeholder="optional comma list"
              />
            </Field>
            {form.webhookProvider === "github" ? (
              <Field label="signature header">
                <Input value="X-Hub-Signature-256" className="h-8 font-mono text-xs" readOnly />
              </Field>
            ) : (
              <Field label="tolerance seconds">
                <Input
                  value={form.webhookToleranceSeconds}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, webhookToleranceSeconds: event.target.value }))
                  }
                  className="h-8 font-mono text-xs"
                  placeholder="default"
                />
              </Field>
            )}
            <div className="md:col-span-4">
              <Field label="secretRef">
                <Input
                  value={form.webhookSecretRef}
                  onChange={(event) => setForm((current) => ({ ...current, webhookSecretRef: event.target.value }))}
                  className="h-8 font-mono text-xs"
                  placeholder={webhookSecretRefPlaceholder(form.webhookProvider)}
                />
              </Field>
            </div>
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
        {isReadinessSource(form.sourceType) ? (
          <div className="grid gap-3">
            <div className="grid gap-3 md:grid-cols-[160px_minmax(0,1fr)_minmax(0,1fr)]">
              <Field label="resource type">
                <Input
                  value={readinessResourceType(form.sourceType)}
                  className="h-8 font-mono text-xs"
                  readOnly
                />
              </Field>
              <Field label="resource id">
                <Input
                  value={form.resourceId}
                  onChange={(event) => setForm((current) => ({ ...current, resourceId: event.target.value }))}
                  className="h-8 font-mono text-xs"
                  placeholder={readinessResourceIdPlaceholder(form.sourceType)}
                />
              </Field>
              <Field label="resource uri">
                <Input
                  value={form.resourceUri}
                  onChange={(event) => setForm((current) => ({ ...current, resourceUri: event.target.value }))}
                  className="h-8 font-mono text-xs"
                  placeholder="optional"
                />
              </Field>
            </div>
            <div className="grid gap-3 md:grid-cols-[140px_180px_minmax(0,1fr)_160px]">
              <label className="flex items-center gap-2 pt-5 text-xs text-slate-600">
                <Checkbox
                  checked={form.watchEnabled}
                  onCheckedChange={(checked) => setForm((current) => ({ ...current, watchEnabled: checked === true }))}
                />
                watch enabled
              </label>
              <Field label="watch adapter">
                <Select
                  value={form.watchAdapter}
                  onValueChange={(value) =>
                    setForm((current) => ({ ...current, watchAdapter: value as "local_path" | "database_registry" }))
                  }
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="local_path">local_path</SelectItem>
                    <SelectItem value="database_registry">database_registry</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              {form.watchAdapter === "local_path" ? (
                <>
                  <Field label="watch path">
                    <Input
                      value={form.watchPath}
                      onChange={(event) => setForm((current) => ({ ...current, watchPath: event.target.value }))}
                      className="h-8 font-mono text-xs"
                      placeholder="E:/data/incoming/reads.fastq"
                    />
                  </Field>
                  <Field label="stability seconds">
                    <Input
                      value={form.watchStabilitySeconds}
                      onChange={(event) =>
                        setForm((current) => ({ ...current, watchStabilitySeconds: event.target.value }))
                      }
                      className="h-8 font-mono text-xs"
                      placeholder="0"
                    />
                  </Field>
                </>
              ) : (
                <div className="self-end text-xs text-slate-500 md:col-span-2">
                  database_registry watches the registered database status.
                </div>
              )}
            </div>
          </div>
        ) : null}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3">
          <div className="text-xs text-slate-500">
            {form.sourceType === "webhook" ? "Webhook definitions use signed inbox delivery and redacted secret references." : "Definitions use typed trigger specs without advanced JSON fallback."}
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
  if (form.sourceType === "webhook") {
    const eventTypes = commaLabels(form.webhookEventTypes);
    const actions = commaLabels(form.webhookActions);
    const secretRef = form.webhookSecretRef.trim();
    if (eventTypes.length === 0) return "WORKFLOW_TRIGGER_WEBHOOK_EVENT_TYPES_REQUIRED";
    if (!secretRef) return "WORKFLOW_TRIGGER_SIGNATURE_SECRET_REF_REQUIRED";
    const signature: Extract<
      WorkflowTriggerDefinitionCreateRequest["triggerSpec"],
      { provider: WorkflowTriggerWebhookProvider }
    >["signature"] = {
      provider: form.webhookProvider,
      required: true,
      secretRef,
    };
    const tolerance = form.webhookToleranceSeconds.trim();
    if (form.webhookProvider !== "github" && tolerance) {
      const toleranceSeconds = Number(tolerance);
      if (!Number.isInteger(toleranceSeconds) || toleranceSeconds < 1 || toleranceSeconds > 3600) {
        return "WORKFLOW_TRIGGER_SIGNATURE_TOLERANCE_OUT_OF_RANGE";
      }
      signature.toleranceSeconds = toleranceSeconds;
    }
    return {
      name,
      sourceType: "webhook",
      serverId,
      enabled: form.enabled,
      runSpec,
      triggerSpec: {
        provider: form.webhookProvider,
        eventMatch: {
          eventTypes,
          ...(actions.length ? { actions } : {}),
        },
        signature,
      },
    };
  }
  if (isReadinessSource(form.sourceType)) {
    const resourceId = form.resourceId.trim();
    const resourceUri = form.resourceUri.trim();
    if (!resourceId) return "WORKFLOW_TRIGGER_READINESS_RESOURCE_ID_REQUIRED";
    const watch = readinessWatchSpec(form);
    if (typeof watch === "string") return watch;
    return {
      name,
      sourceType: form.sourceType,
      serverId,
      enabled: form.enabled,
      runSpec,
      triggerSpec: {
        resource: {
          type: readinessResourceType(form.sourceType),
          id: resourceId,
          ...(resourceUri ? { uri: resourceUri } : {}),
          ...(watch ? { watch } : {}),
        },
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

function isReadinessSource(sourceType: WorkflowTriggerDefinitionSource): sourceType is "dataset" | "file" | "database_ready" {
  return sourceType === "dataset" || sourceType === "file" || sourceType === "database_ready";
}

function readinessResourceType(sourceType: "dataset" | "file" | "database_ready") {
  if (sourceType === "database_ready") return "database";
  return sourceType;
}

function readinessResourceIdPlaceholder(sourceType: WorkflowTriggerDefinitionSource) {
  if (sourceType === "database_ready") return "database:blast-nt";
  if (sourceType === "file") return "file:/incoming/reads.fastq";
  return "dataset:reads";
}

function readinessWatchSpec(form: DefinitionFormState) {
  if (!form.watchEnabled) return null;
  if (form.watchAdapter === "database_registry") {
    return { enabled: true, adapter: "database_registry" as const };
  }
  const path = form.watchPath.trim();
  if (!path) return "WORKFLOW_TRIGGER_WATCH_PATH_REQUIRED";
  const stabilityText = form.watchStabilitySeconds.trim();
  const stabilitySeconds = stabilityText ? Number(stabilityText) : 0;
  if (!Number.isInteger(stabilitySeconds) || stabilitySeconds < 0 || stabilitySeconds > 86400) {
    return "WORKFLOW_TRIGGER_WATCH_STABILITY_SECONDS_OUT_OF_RANGE";
  }
  return {
    enabled: true,
    adapter: "local_path" as const,
    path,
    ...(stabilitySeconds > 0 ? { stabilitySeconds } : {}),
  };
}

function commaLabels(value: string) {
  return value
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
}

function webhookEventTypesPlaceholder(provider: WorkflowTriggerWebhookProvider) {
  if (provider === "slack") return "app_mention";
  if (provider === "stripe") return "checkout.session.completed";
  return "push";
}

function webhookSecretRefPlaceholder(provider: WorkflowTriggerWebhookProvider) {
  if (provider === "slack") return "env://H2OMETA_SLACK_SIGNING_SECRET";
  if (provider === "stripe") return "env://H2OMETA_STRIPE_WEBHOOK_SECRET";
  return "env://H2OMETA_GITHUB_WEBHOOK_SECRET";
}
