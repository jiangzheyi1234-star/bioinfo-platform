"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Archive,
  Check,
  CheckCircle2,
  CircleDot,
  Download,
  FileCode2,
  Fingerprint,
  GitCommitHorizontal,
  MinusCircle,
  Package,
  Server,
  ShieldAlert,
  Sparkles,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import type {
  PluginCenterExtensionItem,
  PluginCenterManagedManifestAction,
  PluginCenterPermission,
  PluginCenterPlacement,
} from "./plugin-center-model";

export type PluginCenterTargetContext = {
  profileId: string;
  serverId: string;
  label: string;
  connected: boolean;
  trusted: boolean;
  loading: boolean;
};

type PluginCenterExtensionDetailsProps = {
  actionError?: string;
  busy?: boolean;
  item: PluginCenterExtensionItem | null;
  open: boolean;
  pendingAction: string | null;
  target: PluginCenterTargetContext;
  onActionConfirm: (item: PluginCenterExtensionItem, action: string, targetServerId: string) => void;
  onActionRequest: (item: PluginCenterExtensionItem, action: string) => void;
  onOpenChange: (open: boolean) => void;
};

export function PluginCenterExtensionDetails({
  actionError = "",
  busy = false,
  item,
  onActionConfirm,
  onActionRequest,
  onOpenChange,
  open,
  pendingAction,
  target,
}: PluginCenterExtensionDetailsProps) {
  const [confirmedKey, setConfirmedKey] = useState("");
  useEffect(() => setConfirmedKey(""), [item?.id, open, pendingAction]);

  const managedActions = useMemo(() => availableManagedActions(item), [item]);
  const selectedAction = managedActions.find((action) => action.id === pendingAction) || null;
  if (!item) return null;

  const manifest = item.manifest;
  const targetRequired = manifest.installTargets.some((installTarget) => installTarget.requiresServerProfile);
  const actionTarget: PluginCenterTargetContext = targetRequired
    ? target
    : {
        profileId: "",
        serverId: "",
        label: manifest.installTargets[0]?.label || "本地控制面",
        connected: true,
        trusted: true,
        loading: false,
      };
  const targetMissing = targetRequired && !target.serverId;
  const mutationActive = item.installState === "installing" || item.installState === "updating";
  const actionUnavailable = Boolean(pendingAction && !selectedAction);
  const confirmationKey = [item.id, pendingAction || "", actionTarget.serverId, actionTarget.connected, actionTarget.trusted].join(":");
  const confirmed = confirmedKey === confirmationKey;
  const trustMissing = targetRequired && !actionTarget.trusted;
  const confirmDisabled = !confirmed || busy || mutationActive || targetMissing || trustMissing || actionUnavailable;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100vh-2rem)] max-w-5xl overflow-hidden rounded-lg p-0">
        <DialogHeader className="border-b border-slate-200 px-5 py-4 pr-12">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <DialogTitle className="truncate text-base">{item.name}</DialogTitle>
              <DialogDescription className="mt-1">{item.summary}</DialogDescription>
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-600">
              <span className="font-mono">{manifest.schemaVersion}</span>
              <span className={cn("rounded-md px-2 py-1 font-medium", healthTone(item.health))}>{item.healthLabel}</span>
            </div>
          </div>
        </DialogHeader>

        <div className="grid min-h-0 overflow-y-auto lg:grid-cols-[minmax(0,1.35fr)_minmax(18rem,0.65fr)]">
          <div className="min-w-0 divide-y divide-slate-200 lg:border-r lg:border-slate-200">
            <section className="grid gap-5 p-5 sm:grid-cols-2" aria-labelledby="plugin-detail-overview">
              <div>
                <SectionHeading id="plugin-detail-overview" icon={Package} label="版本与安装位置" />
                <DefinitionList
                  rows={[
                    ["当前版本", item.installedVersion || "未安装"],
                    ["最新版本", manifest.distribution.latestVersion || "内置"],
                    ["Placement", placementLabel(manifest.placement)],
                    ["Registry", manifest.registryId],
                  ]}
                />
              </div>
              <div>
                <SectionHeading icon={Server} label="目标" />
                <div className="mt-3 flex items-start gap-2">
                  <CircleDot
                    className={cn(
                      "mt-0.5 h-4 w-4 shrink-0",
                      actionTarget.loading ? "text-slate-400" : actionTarget.connected ? "text-emerald-600" : "text-amber-600"
                    )}
                  />
                  <div className="min-w-0">
                    <div className="break-words text-sm font-medium text-slate-900">
                      {actionTarget.loading ? "正在读取 active server profile" : actionTarget.label}
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                      {actionTarget.loading ? "连接状态待确认" : actionTarget.connected ? "已连接" : "未连接"}
                      {actionTarget.profileId ? ` · ${actionTarget.profileId}` : ""}
                    </div>
                    {!actionTarget.loading ? (
                      <div className={cn("mt-1 text-xs", actionTarget.trusted ? "text-emerald-700" : "text-amber-700")}>
                        Host key {actionTarget.trusted ? "已信任" : "待确认"}
                      </div>
                    ) : null}
                  </div>
                </div>
                <div className="mt-3 space-y-2">
                  {manifest.installTargets.map((installTarget) => (
                    <div key={`${installTarget.kind}:${installTarget.label}`} className="flex items-center justify-between gap-3 text-xs">
                      <span className="text-slate-600">{installTarget.label}</span>
                      <span className="font-mono text-slate-500">{installTarget.kind}</span>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            <section className="p-5" aria-labelledby="plugin-detail-package">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <SectionHeading id="plugin-detail-package" icon={Archive} label="分发包" />
                <div className="flex flex-wrap gap-1.5 text-[11px] text-slate-600">
                  <span className="rounded-md bg-slate-100 px-2 py-1">{manifest.distribution.mode}</span>
                  <span className="rounded-md bg-slate-100 px-2 py-1">{manifest.distribution.channel}</span>
                  <span className="rounded-md bg-slate-100 px-2 py-1">{manifest.distribution.delivery}</span>
                  {manifest.distribution.immutable ? (
                    <span className="rounded-md bg-emerald-50 px-2 py-1 text-emerald-700">immutable</span>
                  ) : null}
                </div>
              </div>
              {manifest.distribution.variants.length ? (
                <div className="mt-4 divide-y divide-slate-200 border-y border-slate-200">
                  {manifest.distribution.variants.map((variant) => (
                    <div key={`${variant.platform}:${variant.archiveName}`} className="space-y-3 py-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="min-w-0">
                          <div className="break-all text-sm font-medium text-slate-900">{variant.archiveName}</div>
                          <div className="mt-1 text-xs text-slate-500">
                            v{variant.version} · {variant.platform} · {manifest.distribution.packageType} · {formatBytes(variant.sizeBytes)}
                          </div>
                        </div>
                        <Availability available={variant.downloadAvailable} icon={Download} label="下载" />
                      </div>
                      <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-2 text-xs">
                        <Fingerprint className="mt-0.5 h-3.5 w-3.5 text-slate-400" />
                        <code className="break-all text-slate-700">SHA-256 {variant.sha256}</code>
                        <GitCommitHorizontal className="mt-0.5 h-3.5 w-3.5 text-slate-400" />
                        <span className="break-all text-slate-600">
                          {variant.sourceCommit} · builder {variant.builderId}
                        </span>
                      </div>
                      <div className="grid gap-2 sm:grid-cols-2">
                        <MetadataAvailability available={variant.sbomAvailable} label="SBOM" />
                        <MetadataAvailability available={variant.provenanceAvailable} label="Provenance" />
                        <MetadataAvailability available={variant.attestationAvailable} label="Attestation" />
                        <MetadataAvailability available={variant.signatureAvailable} label="Signature" />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-4 text-sm text-slate-500">该 manifest 未声明可下载的 package variant。</p>
              )}
              <p className="mt-3 text-xs text-slate-500">
                metadata available 仅表示元数据已发布，不代表签名、证明或制品已经通过安装策略验证。
              </p>
            </section>

            <section className="p-5" aria-labelledby="plugin-detail-compatibility">
              <SectionHeading id="plugin-detail-compatibility" icon={FileCode2} label="兼容性" />
              <div className="mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-2">
                {Object.entries(manifest.compatibility).map(([key, value]) => (
                  <div key={key} className="grid grid-cols-[minmax(7rem,0.45fr)_minmax(0,1fr)] gap-3 border-b border-slate-100 py-1.5 text-xs">
                    <span className="font-medium text-slate-600">{key}</span>
                    <span className="break-words text-slate-800">{formatContractValue(value)}</span>
                  </div>
                ))}
              </div>
            </section>
          </div>

          <aside className="min-w-0 divide-y divide-slate-200 bg-slate-50/60">
            <section className="p-5" aria-labelledby="plugin-detail-permissions">
              <SectionHeading id="plugin-detail-permissions" icon={ShieldAlert} label="权限风险" />
              <div className="mt-3 space-y-3">
                {manifest.permissions.length ? (
                  manifest.permissions.map((permission) => <PermissionRow key={permission.id} permission={permission} />)
                ) : (
                  <p className="text-sm text-slate-500">未声明额外权限。</p>
                )}
              </div>
            </section>

            <section className="p-5" aria-labelledby="plugin-detail-capabilities">
              <SectionHeading id="plugin-detail-capabilities" icon={Sparkles} label="Capabilities" />
              <div className="mt-3 space-y-2">
                {manifest.capabilities.length ? (
                  manifest.capabilities.map((capability) => (
                    <div key={capability.id} className="flex items-start justify-between gap-3 border-b border-slate-200 pb-2 text-sm last:border-0">
                      <div className="min-w-0">
                        <div className="font-medium text-slate-900">{capability.label}</div>
                        <div className="mt-0.5 break-all font-mono text-[11px] text-slate-500">{capability.id}</div>
                      </div>
                      {capability.agentSelectable ? (
                        <span className="shrink-0 rounded-md bg-blue-50 px-2 py-1 text-[11px] text-blue-700">agent selectable</span>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-slate-500">未声明 capability。</p>
                )}
              </div>
            </section>

            {pendingAction ? (
              <PreflightPanel
                action={selectedAction}
                actionError={actionError}
                busy={busy}
                confirmed={confirmed}
                confirmDisabled={confirmDisabled}
                item={item}
                mutationActive={mutationActive}
                target={actionTarget}
                targetMissing={targetMissing}
                unavailable={actionUnavailable}
                onConfirmChange={(next) => setConfirmedKey(next ? confirmationKey : "")}
                onRun={() => onActionConfirm(item, pendingAction, actionTarget.serverId)}
              />
            ) : (
              <section className="p-5" aria-labelledby="plugin-detail-actions">
                <SectionHeading id="plugin-detail-actions" icon={Check} label="可用操作" />
                <div className="mt-3 flex flex-wrap gap-2">
                  {managedActions.map((action) => (
                    <Button
                      key={action.id}
                      type="button"
                      size="sm"
                      variant={action.id === "uninstall" ? "destructive" : "outline"}
                      disabled={busy || mutationActive}
                      onClick={() => onActionRequest(item, action.id)}
                    >
                      {action.label}
                    </Button>
                  ))}
                  {managedActions.length === 0 ? <span className="text-sm text-slate-500">没有可执行的 managed action。</span> : null}
                </div>
              </section>
            )}
          </aside>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function PreflightPanel({
  action,
  actionError,
  busy,
  confirmed,
  confirmDisabled,
  item,
  mutationActive,
  onConfirmChange,
  onRun,
  target,
  targetMissing,
  unavailable,
}: {
  action: PluginCenterManagedManifestAction | null;
  actionError: string;
  busy: boolean;
  confirmed: boolean;
  confirmDisabled: boolean;
  item: PluginCenterExtensionItem;
  mutationActive: boolean;
  onConfirmChange: (confirmed: boolean) => void;
  onRun: () => void;
  target: PluginCenterTargetContext;
  targetMissing: boolean;
  unavailable: boolean;
}) {
  return (
    <section className="p-5" aria-labelledby="plugin-detail-preflight">
      <SectionHeading id="plugin-detail-preflight" icon={AlertTriangle} label={`${actionLabel(action?.id || "操作")}预检`} />
      {action ? (
        <div className="mt-3 space-y-3 text-xs text-slate-600">
          <div className="grid grid-cols-[5rem_minmax(0,1fr)] gap-2">
            <span>Driver</span>
            <code className="break-all text-slate-800">{action.driver}</code>
            <span>Operation</span>
            <code className="break-all text-slate-800">{action.operation || action.id}</code>
            <span>目标</span>
            <span className="break-words text-slate-800">{target.label}</span>
            <span>Host key</span>
            <span className={target.trusted ? "text-emerald-700" : "text-amber-700"}>
              {target.trusted ? "已信任" : "待确认"}
            </span>
            <span>风险</span>
            <span className={cn("w-fit rounded-md px-2 py-0.5 font-medium", riskTone(action.risk || "medium"))}>
              {action.risk || "medium"}
            </span>
          </div>
          <div className="flex items-start gap-2 border-t border-slate-200 pt-3">
            <Checkbox
              id={`confirm-extension-${item.id}-${action.id}`}
              checked={confirmed}
              onCheckedChange={(checked) => onConfirmChange(checked === true)}
            />
            <Label htmlFor={`confirm-extension-${item.id}-${action.id}`} className="text-xs font-normal leading-5 text-slate-700">
              我已核对目标、权限风险、package variant 与 SHA-256，并确认执行{actionLabel(action.id)}。
            </Label>
          </div>
          {targetMissing ? <p className="text-red-600">该 action 需要 active server profile，当前没有可执行目标。</p> : null}
          {!targetMissing && !target.trusted ? (
            <p className="text-red-600">请先在 SSH 连接面板确认该目标的 Host key，再执行此操作。</p>
          ) : null}
          {!target.connected && !targetMissing ? <p className="text-amber-700">目标未连接；确认后将先打开连接流程，不会直接执行。</p> : null}
          {mutationActive ? <p className="text-amber-700">该插件已有安装或更新任务，当前不能重复提交。</p> : null}
        </div>
      ) : (
        <p className="mt-3 text-sm text-red-600">
          {unavailable ? "v2 manifest 未声明此 managed action，操作已阻止。" : "无法读取 managed action。"}
        </p>
      )}
      {actionError ? (
        <p className="mt-3 text-sm text-red-700" role="alert" aria-live="assertive">
          {actionError}
        </p>
      ) : null}
      <Button type="button" className="mt-4 w-full" disabled={confirmDisabled} onClick={onRun}>
        {busy ? "正在提交" : !target.connected && !targetMissing ? "核对并连接目标" : `确认${actionLabel(action?.id || "操作")}`}
      </Button>
    </section>
  );
}

function SectionHeading({ id, icon: Icon, label }: { id?: string; icon: typeof Package; label: string }) {
  return (
    <h2 id={id} className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-700">
      <Icon className="h-4 w-4 text-slate-500" strokeWidth={1.6} />
      {label}
    </h2>
  );
}

function DefinitionList({ rows }: { rows: Array<[string, string]> }) {
  return (
    <dl className="mt-3 space-y-2 text-sm">
      {rows.map(([label, value]) => (
        <div key={label} className="grid grid-cols-[6rem_minmax(0,1fr)] gap-3">
          <dt className="text-slate-500">{label}</dt>
          <dd className="break-words font-medium text-slate-900">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function PermissionRow({ permission }: { permission: PluginCenterPermission }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-slate-200 pb-3 last:border-0 last:pb-0">
      <div className="min-w-0">
        <div className="break-words text-sm font-medium text-slate-900">{permission.description || permission.id}</div>
        {permission.description ? <div className="mt-0.5 break-all font-mono text-[11px] text-slate-500">{permission.id}</div> : null}
      </div>
      <span className={cn("shrink-0 rounded-md px-2 py-1 text-[11px] font-medium", riskTone(permission.risk))}>
        {permission.risk}
      </span>
    </div>
  );
}

function MetadataAvailability({ available, label }: { available: boolean; label: string }) {
  const Icon = available ? CheckCircle2 : MinusCircle;
  return (
    <div className={cn("flex items-center gap-2 text-xs", available ? "text-emerald-700" : "text-slate-500")}>
      <Icon className="h-3.5 w-3.5" />
      <span>{label} metadata {available ? "available" : "unavailable"}</span>
    </div>
  );
}

function Availability({ available, icon: Icon, label }: { available: boolean; icon: typeof Download; label: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs", available ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500")}>
      <Icon className="h-3.5 w-3.5" />
      {label}{available ? "可用" : "不可用"}
    </span>
  );
}

function availableManagedActions(item: PluginCenterExtensionItem | null): PluginCenterManagedManifestAction[] {
  if (!item) return [];
  return item.manifest.actions
    .filter((action): action is PluginCenterManagedManifestAction => action.type === "managed-extension-action")
    .filter((action) => item.actions.includes(action.id as PluginCenterExtensionItem["actions"][number]))
    .filter((action) => action.id !== "update" || item.updateAvailable === true);
}

function placementLabel(placement: PluginCenterPlacement): string {
  if (placement === "control-plane") return "Control plane";
  if (placement === "remote-executor") return "Remote executor";
  if (placement === "data-only") return "Data only";
  return "Control plane + remote executor";
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  const units = ["KiB", "MiB", "GiB", "TiB"];
  let value = size / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && value >= 1024; index += 1) {
    value /= 1024;
    unit = units[index];
  }
  return `${value >= 10 ? value.toFixed(1) : value.toFixed(2)} ${unit}`;
}

function formatContractValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(formatContractValue).join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

function actionLabel(action: string): string {
  if (action === "install") return "安装";
  if (action === "repair") return "修复";
  if (action === "update") return "更新";
  if (action === "uninstall") return "卸载";
  return action;
}

function riskTone(risk: string): string {
  if (risk === "destructive") return "bg-red-100 text-red-800";
  if (risk === "high") return "bg-orange-100 text-orange-800";
  if (risk === "medium") return "bg-amber-100 text-amber-800";
  return "bg-emerald-100 text-emerald-800";
}

function healthTone(health: PluginCenterExtensionItem["health"]): string {
  if (health === "ready") return "bg-emerald-50 text-emerald-700";
  if (health === "warning") return "bg-amber-50 text-amber-700";
  if (health === "failed") return "bg-red-50 text-red-700";
  return "bg-slate-100 text-slate-600";
}
