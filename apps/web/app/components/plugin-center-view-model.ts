"use client";

import type { RunnerRepairStatus } from "./ssh-shell-model";
import { TOOL_PREPARE_ACTIVE_STATUSES, type ToolPrepareJob, type ToolPrepareJobQueue } from "./tools-page-model";
import {
  isActiveRemoteProvisioningJob,
  type PluginCenterExtensionItem,
  type PluginCenterTask,
  type RemoteProvisioningJob,
  type RemoteProvisioningJobQueue,
  type ServerProfile,
} from "./plugin-center-model";

type BuildPluginCenterExtensionsInput = {
  status: RunnerRepairStatus | null;
  activeServerProfile: ServerProfile | null;
  activeProvisioningJob: RemoteProvisioningJob | null;
  activeToolPrepareTaskCount: number;
  provisioningQueue: RemoteProvisioningJobQueue | null;
  toolPrepareQueue: ToolPrepareJobQueue | null;
};

export function buildPluginCenterExtensions({
  activeProvisioningJob,
  activeServerProfile,
  activeToolPrepareTaskCount,
  provisioningQueue,
  status,
  toolPrepareQueue,
}: BuildPluginCenterExtensionsInput): PluginCenterExtensionItem[] {
  const connected = Boolean(status?.connected);
  const runnerReady = Boolean(status?.runner?.ready || activeServerProfile?.runner.ready);
  const runnerVersion = activeServerProfile?.runner.installedVersion || "";
  const workflowRuntime = workflowRuntimeProjection(activeServerProfile);
  const provisioningActive = Boolean(activeProvisioningJob);
  const toolQueueTotal = Number(toolPrepareQueue?.total || 0);
  const provisioningTotal = Number(provisioningQueue?.total || 0);

  return [
    {
      id: "h2ometa-remote-runner",
      kind: "runtime",
      slug: "remote-runner",
      name: "远端执行器",
      summary: "通过 SSH 安装、复用和升级 H2OMeta remote runner。",
      description: status?.runner?.message || activeServerProfile?.runner.message || "",
      icon: "server",
      publisher: "H2OMeta",
      sourceId: "h2ometa-official",
      sourceLabel: "由 H2OMeta 提供",
      sourceType: "official",
      categoryIds: ["featured", "runtime"],
      tags: ["ssh", "runner", "runtime"],
      featured: true,
      installed: Boolean(runnerVersion || runnerReady),
      enabled: runnerReady,
      installState: provisioningActive ? "installing" : runnerReady ? "enabled" : connected ? "not_installed" : "disabled",
      installedVersion: runnerVersion,
      requiresRunner: false,
      serverId: activeServerProfile?.serverId || status?.serverId || "",
      health: runnerReady ? "ready" : connected ? "warning" : "unknown",
      healthLabel: runnerReady ? "已就绪" : connected ? "可安装" : "未连接",
      detailLabel: connected ? status?.displayTarget || status?.host || "SSH 已连接" : "需要 SSH",
      primaryAction: runnerReady ? "manage" : "install",
      primaryActionLabel: provisioningActive ? "安装中" : runnerReady ? "管理" : connected ? "安装" : "连接",
      actions: runnerReady ? ["manage", "update"] : ["install"],
      capabilities: [
        { id: "remote-bootstrap", label: "远端 bootstrap", operation: "ensure-runner" },
        { id: "runner-health", label: "健康检查", operation: "diagnostics" },
      ],
    },
    {
      id: "h2ometa-workflow-runtime",
      kind: "runtime",
      slug: "workflow-runtime",
      name: "Workflow Runtime",
      summary: "托管 Snakemake、conda-pack runtime 和 workflow profile。",
      icon: "boxes",
      publisher: "H2OMeta",
      sourceId: "remote-environment",
      sourceLabel: "远端环境",
      sourceType: "remote",
      categoryIds: ["runtime"],
      tags: ["snakemake", "conda-pack", "profile"],
      featured: false,
      installed: workflowRuntime.ready || runnerReady,
      enabled: workflowRuntime.ready,
      installState: workflowRuntime.ready ? "enabled" : runnerReady ? "installed" : "disabled",
      installedVersion: workflowRuntime.version,
      requiresRunner: true,
      serverId: activeServerProfile?.serverId || "",
      health: workflowRuntime.ready ? "ready" : runnerReady ? "warning" : "unknown",
      healthLabel: workflowRuntime.label,
      detailLabel: workflowRuntime.detail,
      manageHref: "/workflows/plugins",
      primaryAction: "manage",
      primaryActionLabel: "查看",
      actions: ["manage"],
      capabilities: [
        { id: "snakemake-runtime", label: "Snakemake runtime" },
        { id: "workflow-profile", label: "Workflow profile" },
      ],
    },
    {
      id: "h2ometa-tool-directory",
      kind: "tool",
      slug: "tool-directory",
      name: "工具插件",
      summary: "管理 Bioconda、conda-forge 与 Snakemake wrapper 工具。",
      icon: "package",
      publisher: "H2OMeta",
      sourceId: "tool-catalog",
      sourceLabel: "工具目录",
      sourceType: "bioconda",
      categoryIds: ["featured", "workflow-tools"],
      tags: ["bioconda", "conda-forge", "snakemake"],
      featured: true,
      installed: toolQueueTotal > 0 || runnerReady,
      enabled: runnerReady,
      installState: activeToolPrepareTaskCount > 0 ? "installing" : runnerReady ? "enabled" : "disabled",
      requiresRunner: true,
      health: activeToolPrepareTaskCount > 0 ? "warning" : runnerReady ? "ready" : "unknown",
      healthLabel: activeToolPrepareTaskCount > 0 ? `${activeToolPrepareTaskCount} 个任务运行中` : runnerReady ? "可用" : "等待 runner",
      detailLabel: toolQueueTotal ? `${toolQueueTotal} 个准备任务` : "打开工具页管理",
      manageHref: "/workflows/tools",
      primaryAction: "manage",
      primaryActionLabel: "打开",
      actions: ["manage", "install"],
      capabilities: [
        { id: "tool-search", label: "工具搜索" },
        { id: "tool-prepare", label: "合同验证", operation: "createToolPrepareJob" },
      ],
    },
    {
      id: "h2ometa-tool-packs",
      kind: "tool-pack",
      slug: "tool-packs",
      name: "Tool Packs",
      summary: "导入、启用和复用经过验收的工具能力包。",
      icon: "layers",
      publisher: "H2OMeta",
      sourceId: "local-import",
      sourceLabel: "本地导入",
      sourceType: "tool-pack",
      categoryIds: ["workflow-tools", "productivity"],
      tags: ["tool-pack", "acceptance", "reuse"],
      featured: false,
      installed: false,
      enabled: false,
      installState: "not_installed",
      requiresRunner: true,
      health: "unknown",
      healthLabel: "待接入",
      detailLabel: "复用现有 tool-pack API",
      manageHref: "/workflows/tools",
      primaryAction: "manage",
      primaryActionLabel: "管理",
      actions: ["manage", "install", "enable"],
      capabilities: [{ id: "tool-pack-import", label: "能力包导入" }],
    },
    {
      id: "h2ometa-database-packs",
      kind: "database-pack",
      slug: "database-packs",
      name: "数据库包",
      summary: "管理参考数据库、资源绑定和数据库验收状态。",
      icon: "database",
      publisher: "H2OMeta",
      sourceId: "h2ometa-official",
      sourceLabel: "由 H2OMeta 提供",
      sourceType: "official",
      categoryIds: ["data"],
      tags: ["database", "resource", "binding"],
      featured: false,
      installed: false,
      enabled: false,
      installState: "not_installed",
      requiresRunner: true,
      health: "unknown",
      healthLabel: "可配置",
      detailLabel: "进入数据库页",
      manageHref: "/workflows/databases",
      primaryAction: "manage",
      primaryActionLabel: "打开",
      actions: ["manage"],
      capabilities: [{ id: "database-binding", label: "数据库绑定" }],
    },
    {
      id: "h2ometa-operator-skill",
      kind: "skill",
      slug: "operator-skill",
      name: "远端运维技能",
      summary: "把远端 smoke、bootstrap 和诊断入口暴露给 agent 工作流。",
      icon: "sparkles",
      publisher: "H2OMeta",
      sourceId: "h2ometa-official",
      sourceLabel: "由 H2OMeta 提供",
      sourceType: "official",
      categoryIds: ["featured", "governance"],
      tags: ["agent", "smoke", "diagnostics"],
      featured: true,
      installed: true,
      enabled: runnerReady,
      installState: runnerReady ? "enabled" : "installed",
      requiresRunner: true,
      health: runnerReady ? "ready" : "warning",
      healthLabel: runnerReady ? "可用" : "等待 runner",
      detailLabel: "Try in chat 入口预留",
      primaryAction: "try_in_chat",
      primaryActionLabel: "Try in chat",
      actions: ["try_in_chat", "manage"],
      capabilities: [
        { id: "remote-smoke", label: "远端 smoke", agentSelectable: true },
        { id: "bootstrap-diagnostics", label: "Bootstrap 诊断", agentSelectable: true },
      ],
      tryInChat: {
        enabled: runnerReady,
        capabilityId: "remote-smoke",
        promptTemplate: "检查当前 H2OMeta 远端服务器和 runner 状态。",
      },
    },
  ];
}

export function buildPluginCenterTasks(
  provisioningQueue: RemoteProvisioningJobQueue | null,
  toolPrepareQueue: ToolPrepareJobQueue | null
): PluginCenterTask[] {
  const remoteTasks: PluginCenterTask[] = (provisioningQueue?.items || []).map((job) => ({
    id: job.jobId,
    kind: "remote-provisioning",
    target: job.displayTarget || job.serverId || "remote runner",
    action: job.action,
    status: job.status,
    stage: job.stage,
    message: job.message,
    createdAt: job.createdAt,
    updatedAt: job.updatedAt,
    active: isActiveRemoteProvisioningJob(job),
  }));
  const toolTasks: PluginCenterTask[] = (toolPrepareQueue?.items || []).map((job) => ({
    id: job.jobId,
    kind: "tool-prepare",
    target: toolPrepareTarget(job),
    action: "prepare-tool",
    status: job.status,
    stage: job.stage,
    message: job.message,
    createdAt: job.createdAt,
    updatedAt: job.updatedAt,
    active: TOOL_PREPARE_ACTIVE_STATUSES.includes(job.status as (typeof TOOL_PREPARE_ACTIVE_STATUSES)[number]),
    href: "/workflows/tools",
  }));
  return [...remoteTasks, ...toolTasks].sort((left, right) => timestamp(right.updatedAt) - timestamp(left.updatedAt));
}

function workflowRuntimeProjection(profile: ServerProfile | null) {
  const health = profile?.runner.health;
  const workflowRuntime = recordValue(health, "workflowRuntime");
  const ok = booleanValue(workflowRuntime, "ok");
  const version = stringValue(workflowRuntime, "version");
  const snakemakeVersion = stringValue(workflowRuntime, "snakemakeVersion");
  const message = stringValue(workflowRuntime, "message");
  return {
    ready: ok,
    version,
    label: ok ? "已就绪" : profile?.runner.ready ? "需检查" : "等待 runner",
    detail: snakemakeVersion ? `Snakemake ${snakemakeVersion}` : message || "未记录",
  };
}

function toolPrepareTarget(job: ToolPrepareJob): string {
  return String(job.request?.name || job.request?.id || job.toolId || "tool");
}

function recordValue(value: unknown, key: string): Record<string, unknown> | null {
  if (!value || typeof value !== "object") return null;
  const next = (value as Record<string, unknown>)[key];
  return next && typeof next === "object" ? (next as Record<string, unknown>) : null;
}

function stringValue(value: Record<string, unknown> | null, key: string): string {
  const next = value?.[key];
  return typeof next === "string" ? next : "";
}

function booleanValue(value: Record<string, unknown> | null, key: string): boolean {
  return value?.[key] === true;
}

function timestamp(value: string): number {
  const parsed = Date.parse(value || "");
  return Number.isFinite(parsed) ? parsed : 0;
}
