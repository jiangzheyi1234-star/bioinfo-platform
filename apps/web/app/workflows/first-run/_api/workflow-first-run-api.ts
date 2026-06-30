"use client";

import { requestLocalApiJson } from "@/app/lib/local-api-client";

import type { FirstRunFinalization, FirstRunStatus, FirstRunValidationCard } from "../_domain/first-run-types";

export async function fetchFirstRunStatus(
  options: { refresh?: boolean; runId?: string; serverId?: string } = {}
): Promise<FirstRunStatus> {
  const query = new URLSearchParams();
  if (options.serverId) query.set("serverId", options.serverId);
  if (options.runId) query.set("runId", options.runId);
  if (options.refresh) query.set("refresh", "true");
  const response = await requestLocalApiJson<{ data: FirstRunStatus }>(
    "GET",
    `/api/v1/first-run/status${queryString(query)}`,
    { cache: "no-store", timeoutMs: 30_000 }
  );
  return response.data;
}

export async function fetchFirstRunValidationCard(
  runId: string,
  options: { serverId?: string } = {}
): Promise<FirstRunValidationCard> {
  const query = new URLSearchParams();
  if (options.serverId) query.set("serverId", options.serverId);
  const response = await requestLocalApiJson<{ data: FirstRunValidationCard }>(
    "GET",
    `/api/v1/first-run/runs/${encodeURIComponent(runId)}/validation-card${queryString(query)}`,
    { cache: "no-store", timeoutMs: 30_000 }
  );
  return response.data;
}

export async function finalizeFirstRun(
  runId: string,
  options: { actor?: string; serverId?: string } = {}
): Promise<FirstRunFinalization> {
  const response = await requestLocalApiJson<{ data: FirstRunFinalization }>(
    "POST",
    `/api/v1/first-run/runs/${encodeURIComponent(runId)}/finalize`,
    {
      body: {
        ...(options.serverId ? { serverId: options.serverId } : {}),
        ...(options.actor ? { actor: options.actor } : {}),
      },
      cache: "no-store",
      timeoutMs: 60_000,
    }
  );
  return response.data;
}

function queryString(query: URLSearchParams) {
  const value = query.toString();
  return value ? `?${value}` : "";
}
