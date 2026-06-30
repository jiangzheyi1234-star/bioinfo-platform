"use client";

import { apiBase, requestLocalApiJson } from "@/app/lib/local-api-client";

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

export async function downloadFirstRunValidationCard({
  runId,
  serverId,
}: {
  runId: string;
  serverId?: string;
}) {
  downloadLocalApiFile(firstRunValidationCardJsonDownloadPath(runId, { serverId }));
}

export async function downloadFirstRunValidationCardMarkdown({
  runId,
  serverId,
}: {
  runId: string;
  serverId?: string;
}) {
  downloadLocalApiFile(firstRunValidationCardMarkdownDownloadPath(runId, { serverId }));
}

export async function downloadFirstRunHandoffManifest({
  runId,
  serverId,
}: {
  runId: string;
  serverId?: string;
}) {
  downloadLocalApiFile(firstRunPilotHandoffMarkdownDownloadPath(runId, { serverId }));
}

export function firstRunValidationCardJsonDownloadPath(runId: string, options: { serverId?: string } = {}) {
  return firstRunDownloadPath(runId, "validation-card.json", options);
}

export function firstRunValidationCardMarkdownDownloadPath(runId: string, options: { serverId?: string } = {}) {
  return firstRunDownloadPath(runId, "validation-card.md", options);
}

export function firstRunPilotHandoffMarkdownDownloadPath(runId: string, options: { serverId?: string } = {}) {
  return firstRunDownloadPath(runId, "pilot-handoff.md", options);
}

function queryString(query: URLSearchParams) {
  const value = query.toString();
  return value ? `?${value}` : "";
}

function firstRunDownloadPath(runId: string, filename: string, options: { serverId?: string }) {
  const query = new URLSearchParams();
  if (options.serverId) query.set("serverId", options.serverId);
  return `/api/v1/first-run/runs/${encodeURIComponent(runId)}/${filename}${queryString(query)}`;
}

function downloadLocalApiFile(path: string) {
  const anchor = document.createElement("a");
  anchor.href = `${apiBase()}${path}`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
}
