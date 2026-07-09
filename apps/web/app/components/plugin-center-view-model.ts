"use client";

import { TOOL_PREPARE_ACTIVE_STATUSES, type ToolPrepareJob, type ToolPrepareJobQueue } from "./tools-page-model";
import {
  isActiveRemoteProvisioningJob,
  type PluginCenterTask,
  type RemoteProvisioningJobQueue,
} from "./plugin-center-model";

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

function toolPrepareTarget(job: ToolPrepareJob): string {
  return String(job.request?.name || job.request?.id || job.toolId || "tool");
}

function timestamp(value: string): number {
  const parsed = Date.parse(value || "");
  return Number.isFinite(parsed) ? parsed : 0;
}
