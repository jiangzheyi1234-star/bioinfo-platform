import { cachedAsync } from "@/app/lib/async-cache";
import { requestLocalApiJson } from "@/app/lib/local-api-client";

import type {
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
