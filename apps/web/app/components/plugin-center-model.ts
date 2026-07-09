export const REMOTE_PROVISIONING_ACTIVE_STATUSES = ["queued", "running"] as const;
export const REMOTE_PROVISIONING_TERMINAL_STATUSES = ["succeeded", "failed", "cancelled"] as const;

export type RemoteProvisioningJobAction = "ensure-runner" | "start-runner" | "upgrade-runner";
export type RemoteProvisioningJobStatus =
  | (typeof REMOTE_PROVISIONING_ACTIVE_STATUSES)[number]
  | (typeof REMOTE_PROVISIONING_TERMINAL_STATUSES)[number]
  | string;

export type RemoteProvisioningJobEvent = {
  eventId: string;
  stage: string;
  level: "info" | "success" | "warning" | "error" | string;
  message: string;
  createdAt: string;
};

export type RemoteProvisioningJob = {
  jobId: string;
  serverId: string;
  displayTarget?: string;
  action: RemoteProvisioningJobAction | string;
  status: RemoteProvisioningJobStatus;
  stage: string;
  message: string;
  createdAt: string;
  updatedAt: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  cancelledAt?: string | null;
  errorCode?: string | null;
  result?: Record<string, unknown> | null;
  events?: RemoteProvisioningJobEvent[];
};

export type RemoteProvisioningJobQueue = {
  items: RemoteProvisioningJob[];
  total: number;
  limit: number;
  offset: number;
  status: string;
  statusCounts: Record<string, number>;
  activeCount: number;
  queuedCount: number;
  runningCount: number;
  activeStatuses: string[];
  terminalStatuses: string[];
};

export type RemoteProvisioningJobResponse = {
  data: RemoteProvisioningJob;
};

export type RemoteProvisioningJobQueueResponse = {
  data: RemoteProvisioningJobQueue;
};

export type ServerProfile = {
  schemaVersion: "server-profile.v1" | string;
  profileId: string;
  serverId: string;
  displayName: string;
  source: string;
  isDefault: boolean;
  configured: boolean;
  connected: boolean;
  connection: {
    authMode: string;
    sshHostAlias: string;
    host: string;
    port: number;
    user: string;
    identityRef: string;
    rememberAuth: boolean;
    autoConnectOnStartup: boolean;
    hasPassword: boolean;
    timeoutSec: number;
  };
  hostKeyTrust: {
    trusted: boolean;
    fingerprintSha256: string;
    knownHostsPath: string;
  };
  provisioning: {
    lastJobId: string;
    lastAction: string;
    lastStatus: string;
    lastUpdatedAt: string;
  };
  diagnostics: {
    lastBundleRef: string;
    lastCheckedAt: string;
  };
  runner: {
    state: string;
    ready: boolean;
    message: string;
    reasonCode: string;
    installedVersion: string;
    runnerMode: string;
    deploymentAction: string;
    servicePort?: number;
    tunnelPort?: number;
    tokenRef: string;
    hasTokenRef: boolean;
    health?: Record<string, unknown> | null;
  };
};

export type ServerProfileList = {
  items: ServerProfile[];
  total: number;
  defaultProfileId: string;
  activeProfileId: string;
};

export type ServerProfileListResponse = {
  data: ServerProfileList;
};

export function isActiveRemoteProvisioningJob(job: RemoteProvisioningJob): boolean {
  return REMOTE_PROVISIONING_ACTIVE_STATUSES.includes(job.status as (typeof REMOTE_PROVISIONING_ACTIVE_STATUSES)[number]);
}
