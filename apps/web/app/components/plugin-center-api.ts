"use client";

import { requestLocalApiJson } from "@/app/lib/local-api-client";

import type {
  RemoteProvisioningJob,
  RemoteProvisioningJobAction,
  RemoteProvisioningJobQueue,
  RemoteProvisioningJobQueueResponse,
  RemoteProvisioningJobResponse,
} from "./plugin-center-model";

export async function createRemoteProvisioningJob(
  serverId: string,
  action: RemoteProvisioningJobAction
): Promise<RemoteProvisioningJob> {
  const response = await requestLocalApiJson<RemoteProvisioningJobResponse>(
    "POST",
    `/api/v1/servers/${encodeURIComponent(serverId)}/remote-provisioning/jobs`,
    {
      body: { action },
      timeoutMs: 10_000,
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
