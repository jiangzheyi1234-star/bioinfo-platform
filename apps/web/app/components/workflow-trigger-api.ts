"use client";

import { cachedAsync, invalidateAsyncCachePrefix } from "@/app/lib/async-cache";
import { requestLocalApiJson } from "@/app/lib/local-api-client";

import type {
  WorkflowTriggerEventList,
  WorkflowTriggerEventListResponse,
  WorkflowTriggerInboxEventList,
  WorkflowTriggerInboxEventListResponse,
  WorkflowTriggerInboxReplayResponse,
  WorkflowTriggerInboxReplayResult,
  WorkflowTriggerList,
  WorkflowTriggerListResponse,
  WorkflowTriggerReadinessObservationEnvelope,
  WorkflowTriggerReadinessObservationResponse,
} from "./workflow-trigger-model";

type WorkflowTriggerFetchOptions = {
  forceRefresh?: boolean;
  serverId?: string;
  state?: string;
  limit?: number;
};

const WORKFLOW_TRIGGERS_CACHE_KEY = "workflow:triggers";
const WORKFLOW_TRIGGER_EVENTS_CACHE_KEY = "workflow:trigger-events";
const WORKFLOW_TRIGGER_INBOX_CACHE_KEY = "workflow:trigger-inbox";
const WORKFLOW_TRIGGER_READINESS_OBSERVATION_CACHE_KEY = "workflow:trigger-readiness-observation";

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

export async function fetchWorkflowTriggerInboxEvents(
  triggerId: string,
  options: WorkflowTriggerFetchOptions = {}
): Promise<WorkflowTriggerInboxEventList> {
  const normalizedTriggerId = triggerId.trim();
  if (!normalizedTriggerId) {
    throw new Error("WORKFLOW_TRIGGER_ID_REQUIRED");
  }
  const key = [
    WORKFLOW_TRIGGER_INBOX_CACHE_KEY,
    options.serverId || "default",
    normalizedTriggerId,
    options.state || "all",
    String(options.limit || 100),
  ].join(":");
  return cachedAsync(key, 10_000, async () => {
    const response = await requestLocalApiJson<WorkflowTriggerInboxEventListResponse>(
      "GET",
      `/api/v1/workflow-triggers/${encodeURIComponent(normalizedTriggerId)}/inbox${triggerQuery(options)}`,
      { cache: "no-store" }
    );
    return { schemaVersion: response.data.schemaVersion, items: response.data.items || [] };
  }, {
    forceRefresh: options.forceRefresh,
  });
}

export async function fetchWorkflowTriggerReadinessObservation(
  triggerId: string,
  options: WorkflowTriggerFetchOptions = {}
): Promise<WorkflowTriggerReadinessObservationEnvelope> {
  const normalizedTriggerId = triggerId.trim();
  if (!normalizedTriggerId) {
    throw new Error("WORKFLOW_TRIGGER_ID_REQUIRED");
  }
  const key = [
    WORKFLOW_TRIGGER_READINESS_OBSERVATION_CACHE_KEY,
    options.serverId || "default",
    normalizedTriggerId,
  ].join(":");
  return cachedAsync(key, 10_000, async () => {
    const response = await requestLocalApiJson<WorkflowTriggerReadinessObservationResponse>(
      "GET",
      `/api/v1/workflow-triggers/${encodeURIComponent(normalizedTriggerId)}/readiness-observation${triggerQuery(options)}`,
      { cache: "no-store" }
    );
    return {
      schemaVersion: response.data.schemaVersion,
      triggerId: response.data.triggerId,
      sourceType: response.data.sourceType,
      observation: response.data.observation || null,
    };
  }, {
    forceRefresh: options.forceRefresh,
  });
}

export async function replayWorkflowTriggerInboxEvent(
  triggerId: string,
  inboxEventId: string
): Promise<WorkflowTriggerInboxReplayResult> {
  const normalizedTriggerId = triggerId.trim();
  const normalizedInboxEventId = inboxEventId.trim();
  if (!normalizedTriggerId) {
    throw new Error("WORKFLOW_TRIGGER_ID_REQUIRED");
  }
  if (!normalizedInboxEventId) {
    throw new Error("WORKFLOW_TRIGGER_INBOX_EVENT_ID_REQUIRED");
  }
  const response = await requestLocalApiJson<WorkflowTriggerInboxReplayResponse>(
    "POST",
    `/api/v1/workflow-triggers/${encodeURIComponent(normalizedTriggerId)}/inbox/${encodeURIComponent(normalizedInboxEventId)}/replay`,
    {
      body: {
        confirmation: "replay-dead-lettered-inbox-event",
        actor: "web-ui",
        reason: "operator requested replay from trigger observability",
      },
      cache: "no-store",
    }
  );
  invalidateAsyncCachePrefix(WORKFLOW_TRIGGER_EVENTS_CACHE_KEY);
  invalidateAsyncCachePrefix(WORKFLOW_TRIGGER_INBOX_CACHE_KEY);
  return response.data;
}

function triggerQuery(options: WorkflowTriggerFetchOptions) {
  const params = new URLSearchParams();
  if (options.forceRefresh) params.set("refresh", "true");
  if (options.serverId) params.set("serverId", options.serverId);
  if (options.state) params.set("state", options.state);
  if (options.limit) params.set("limit", String(options.limit));
  const query = params.toString();
  return query ? `?${query}` : "";
}
