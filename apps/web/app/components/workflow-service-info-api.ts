import { cachedAsync } from "@/app/lib/async-cache";
import { requestLocalApiJson } from "@/app/lib/local-api-client";

import type {
  WorkflowLocalExecutionReadiness,
  WorkflowLocalExecutionReadinessQueue,
  WorkflowLocalExecutionReadinessWorkers,
  WorkflowLocalServiceInfo,
  WorkflowLocalServiceInfoResponse,
  WorkflowProductionGovernanceCheck,
  WorkflowProductionGovernanceReadiness,
} from "./workflow-service-info-model";

const WORKFLOW_SERVICE_INFO_CACHE_KEY = "workflow:service-info";

type FetchWorkflowServiceInfoOptions = {
  forceRefresh?: boolean;
};

export async function fetchWorkflowServiceInfo(
  options: FetchWorkflowServiceInfoOptions = {}
): Promise<WorkflowLocalServiceInfo> {
  return cachedAsync(WORKFLOW_SERVICE_INFO_CACHE_KEY, 10_000, async () => {
    const response = await requestLocalApiJson<WorkflowLocalServiceInfoResponse>(
      "GET",
      "/api/v1/service-info",
      { cache: "no-store" }
    );
    return normalizeWorkflowServiceInfo(response.item);
  }, {
    forceRefresh: options.forceRefresh,
  });
}

function normalizeWorkflowServiceInfo(value: unknown): WorkflowLocalServiceInfo {
  const item = recordValue(value);
  const deployment = recordValue(item.deployment);
  return {
    deployment: {
      mode: stringValue(deployment.mode),
    },
    executionReadiness: normalizeLocalExecutionReadiness(item.executionReadiness),
    productionGovernance: normalizeProductionGovernance(item.productionGovernance),
  };
}

function normalizeProductionGovernance(value: unknown): WorkflowProductionGovernanceReadiness {
  const governance = recordValue(value);
  return {
    schemaVersion: stringValue(governance.schemaVersion),
    currentModeStatus: stringValue(governance.currentModeStatus),
    publicMultiUserStatus: stringValue(governance.publicMultiUserStatus),
    publicMultiUserReady: governance.publicMultiUserReady === true,
    currentModeBlockingCheckIds: stringList(governance.currentModeBlockingCheckIds),
    publicMultiUserBlockingCheckIds: stringList(governance.publicMultiUserBlockingCheckIds),
    checks: Array.isArray(governance.checks)
      ? governance.checks.map(normalizeProductionGovernanceCheck)
      : [],
  };
}

function normalizeProductionGovernanceCheck(value: unknown): WorkflowProductionGovernanceCheck {
  const check = recordValue(value);
  return {
    id: stringValue(check.id),
    status: stringValue(check.status),
    reasonCode: stringValue(check.reasonCode),
    blocksCurrentMode: check.blocksCurrentMode === true,
    requiredFor: stringValue(check.requiredFor),
    evidence: stringList(check.evidence),
  };
}

function normalizeLocalExecutionReadiness(value: unknown): WorkflowLocalExecutionReadiness {
  const readiness = recordValue(value);
  return {
    schemaVersion: stringValue(readiness.schemaVersion),
    connected: readiness.connected === true,
    diagnosticsAvailable: readiness.diagnosticsAvailable === true,
    ready: readiness.ready === true,
    status: stringValue(readiness.status),
    reasonCode: stringValue(readiness.reasonCode),
    serverId: stringValue(readiness.serverId),
    generatedAt: stringValue(readiness.generatedAt),
    queue: normalizeLocalExecutionQueue(readiness.queue),
    workers: normalizeLocalExecutionWorkers(readiness.workers),
    checks: booleanRecord(readiness.checks),
  };
}

function normalizeLocalExecutionQueue(value: unknown): WorkflowLocalExecutionReadinessQueue {
  const queue = recordValue(value);
  return {
    queuedJobs: numberValue(queue.queuedJobs),
    totalQueuedJobs: numberValue(queue.totalQueuedJobs),
    scheduledQueuedJobs: numberValue(queue.scheduledQueuedJobs),
    claimedJobs: numberValue(queue.claimedJobs),
    activeLeases: numberValue(queue.activeLeases),
    resourceWaitJobs: numberValue(queue.resourceWaitJobs),
    oldestQueuedAgeSeconds: optionalNumberValue(queue.oldestQueuedAgeSeconds),
    waitReasons: numberRecord(queue.waitReasons),
  };
}

function normalizeLocalExecutionWorkers(value: unknown): WorkflowLocalExecutionReadinessWorkers {
  const workers = recordValue(value);
  return {
    workerCount: numberValue(workers.workerCount),
    totalSlots: numberValue(workers.totalSlots),
    runningSlots: numberValue(workers.runningSlots),
    idleSlots: numberValue(workers.idleSlots),
    queueDepth: numberValue(workers.queueDepth),
    claimedJobs: numberValue(workers.claimedJobs),
    workerStates: numberRecord(workers.workerStates),
    slotStates: numberRecord(workers.slotStates),
  };
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.trunc(value)) : 0;
}

function optionalNumberValue(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  return numberValue(value);
}

function numberRecord(value: unknown): Record<string, number> {
  const source = recordValue(value);
  return Object.fromEntries(Object.entries(source).map(([key, item]) => [key, numberValue(item)]));
}

function booleanRecord(value: unknown): Record<string, boolean> {
  const source = recordValue(value);
  return Object.fromEntries(Object.entries(source).filter(([, item]) => typeof item === "boolean")) as Record<string, boolean>;
}
