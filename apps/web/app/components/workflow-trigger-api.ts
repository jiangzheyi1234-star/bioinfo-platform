"use client";

import { cachedAsync } from "@/app/lib/async-cache";
import { requestLocalApiJson } from "@/app/lib/local-api-client";

import type {
  WorkflowTriggerEventList,
  WorkflowTriggerEventListResponse,
  WorkflowTriggerList,
  WorkflowTriggerListResponse,
} from "./workflow-trigger-model";

type WorkflowTriggerFetchOptions = {
  forceRefresh?: boolean;
  serverId?: string;
};

const WORKFLOW_TRIGGERS_CACHE_KEY = "workflow:triggers";
const WORKFLOW_TRIGGER_EVENTS_CACHE_KEY = "workflow:trigger-events";

export async function fetchWorkflowTriggers(
  options: WorkflowTriggerFetchOptions = {}
): Promise<WorkflowTriggerList> {
  const key = [WORKFLOW_TRIGGERS_CACHE_KEY, options.serverId || "default"].join(":");
  return cachedAsync(key, 10_000, async () => {
    const response = await requestLocalApiJson<WorkflowTriggerListResponse>(
      "GET",
      `/api/v1/workflow-triggers${triggerQuery(options)}`,
      { cache: "no-store" }
    );
    return { items: response.data.items || [] };
  }, {
    forceRefresh: options.forceRefresh,
  });
}

export async function fetchWorkflowTriggerEvents(
  triggerId: string,
  options: WorkflowTriggerFetchOptions = {}
): Promise<WorkflowTriggerEventList> {
  const normalizedTriggerId = triggerId.trim();
  if (!normalizedTriggerId) {
    throw new Error("WORKFLOW_TRIGGER_ID_REQUIRED");
  }
  const key = [
    WORKFLOW_TRIGGER_EVENTS_CACHE_KEY,
    options.serverId || "default",
    normalizedTriggerId,
  ].join(":");
  return cachedAsync(key, 10_000, async () => {
    const response = await requestLocalApiJson<WorkflowTriggerEventListResponse>(
      "GET",
      `/api/v1/workflow-triggers/${encodeURIComponent(normalizedTriggerId)}/events${triggerQuery(options)}`,
      { cache: "no-store" }
    );
    return { items: response.data.items || [] };
  }, {
    forceRefresh: options.forceRefresh,
  });
}

function triggerQuery(options: WorkflowTriggerFetchOptions) {
  const params = new URLSearchParams();
  if (options.forceRefresh) params.set("refresh", "true");
  if (options.serverId) params.set("serverId", options.serverId);
  const query = params.toString();
  return query ? `?${query}` : "";
}
