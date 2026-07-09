"use client";

import { requestLocalApiJson } from "@/app/lib/local-api-client";

import type {
  PluginCenterExtensionActionRequest,
  PluginCenterExtensionActionResponse,
  PluginCenterExtensionActionResult,
  PluginCenterExtensionList,
  PluginCenterExtensionListResponse,
  RemoteProvisioningJob,
  RemoteProvisioningJobQueue,
  RemoteProvisioningJobQueueResponse,
  RemoteProvisioningJobResponse,
  ServerProfileList,
  ServerProfileListResponse,
} from "./plugin-center-model";

export async function fetchPluginCenterExtensions(signal?: AbortSignal): Promise<PluginCenterExtensionList> {
  const response = await requestLocalApiJson<PluginCenterExtensionListResponse>(
    "GET",
    "/api/v1/plugin-center/extensions",
    { cache: "no-store", signal }
  );
  return response.data;
}

export async function executePluginCenterExtensionAction(
  extensionId: string,
  request: PluginCenterExtensionActionRequest
): Promise<PluginCenterExtensionActionResult> {
  const response = await requestLocalApiJson<PluginCenterExtensionActionResponse>(
    "POST",
    `/api/v1/plugin-center/extensions/${encodeURIComponent(extensionId)}/actions`,
    {
      body: request,
      timeoutMs: request.action === "uninstall" && request.mode === "run" ? 180_000 : 10_000,
    }
  );
  return response.data;
}

export async function fetchRemoteProvisioningJobQueue({
  limit = 8,
  offset = 0,
  signal,
  status = "",
}: {
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
  status?: string;
} = {}): Promise<RemoteProvisioningJobQueue> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (status) params.set("status", status);
  const response = await requestLocalApiJson<RemoteProvisioningJobQueueResponse>(
    "GET",
    `/api/v1/remote-provisioning/jobs?${params.toString()}`,
    { cache: "no-store", signal }
  );
  return response.data;
}

export async function fetchRemoteProvisioningJob(jobId: string): Promise<RemoteProvisioningJob> {
  const response = await requestLocalApiJson<RemoteProvisioningJobResponse>(
    "GET",
    `/api/v1/remote-provisioning/jobs/${encodeURIComponent(jobId)}`,
    { cache: "no-store" }
  );
  return response.data;
}

export async function cancelRemoteProvisioningJob(jobId: string): Promise<RemoteProvisioningJob> {
  const response = await requestLocalApiJson<RemoteProvisioningJobResponse>(
    "POST",
    `/api/v1/remote-provisioning/jobs/${encodeURIComponent(jobId)}/cancel`,
    { body: {} }
  );
  return response.data;
}

export async function fetchServerProfiles(signal?: AbortSignal): Promise<ServerProfileList> {
  const response = await requestLocalApiJson<ServerProfileListResponse>(
    "GET",
    "/api/v1/server-profiles",
    { cache: "no-store", signal }
  );
  return response.data;
}
