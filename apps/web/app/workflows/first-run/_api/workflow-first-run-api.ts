"use client";

import { requestLocalApiJson } from "@/app/lib/local-api-client";

import { firstRunHandoffManifestMarkdown, firstRunValidationCardMarkdown } from "../_domain/first-run-markdown";
import type { FirstRunFinalization, FirstRunValidationCard } from "../_domain/first-run-types";

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
  card,
  resultId,
  runId,
  serverId,
}: {
  card?: FirstRunValidationCard | null;
  resultId: string;
  runId: string;
  serverId?: string;
}) {
  const resolvedCard = card || (await fetchFirstRunValidationCard(runId, { serverId }));
  const blob = new Blob([JSON.stringify(resolvedCard, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${resultId || runId}.validation-card.json`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
export async function downloadFirstRunValidationCardMarkdown({
  card,
  resultId,
  runId,
  serverId,
}: {
  card?: FirstRunValidationCard | null;
  resultId: string;
  runId: string;
  serverId?: string;
}) {
  const resolvedCard = card || (await fetchFirstRunValidationCard(runId, { serverId }));
  downloadTextFile({
    content: firstRunValidationCardMarkdown(resolvedCard),
    filename: `${resultId || runId}.validation-card.md`,
    type: "text/markdown;charset=utf-8",
  });
}

export async function downloadFirstRunHandoffManifest({
  card,
  resultId,
  runId,
  serverId,
}: {
  card?: FirstRunValidationCard | null;
  resultId: string;
  runId: string;
  serverId?: string;
}) {
  const resolvedCard = card || (await fetchFirstRunValidationCard(runId, { serverId }));
  downloadTextFile({
    content: firstRunHandoffManifestMarkdown(resolvedCard),
    filename: `${resultId || runId}.pilot-handoff.md`,
    type: "text/markdown;charset=utf-8",
  });
}

function queryString(query: URLSearchParams) {
  const value = query.toString();
  return value ? `?${value}` : "";
}

function downloadTextFile({ content, filename, type }: { content: string; filename: string; type: string }) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
