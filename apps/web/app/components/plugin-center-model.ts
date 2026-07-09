export const REMOTE_PROVISIONING_ACTIVE_STATUSES = ["queued", "running"] as const;
export const REMOTE_PROVISIONING_TERMINAL_STATUSES = ["succeeded", "failed", "cancelled"] as const;

export const PLUGIN_CENTER_VIEW_MODES = ["plugins", "skills"] as const;
export const PLUGIN_CENTER_CATEGORIES = [
  { id: "featured", label: "Featured" },
  { id: "runtime", label: "Runtime" },
  { id: "workflow-tools", label: "Workflow Tools" },
  { id: "data", label: "Data" },
  { id: "productivity", label: "Productivity" },
  { id: "governance", label: "Governance" },
] as const;

export type PluginCenterViewMode = (typeof PLUGIN_CENTER_VIEW_MODES)[number];
export type PluginCenterCategoryId = (typeof PLUGIN_CENTER_CATEGORIES)[number]["id"];
export type PluginCenterKind = "plugin" | "skill" | "tool" | "tool-pack" | "runtime" | "database-pack";
export type PluginCenterSourceType =
  | "official"
  | "local"
  | "remote"
  | "bioconda"
  | "conda-forge"
  | "snakemake-wrapper"
  | "tool-pack";
export type PluginCenterInstallState =
  | "not_installed"
  | "installed"
  | "enabled"
  | "disabled"
  | "installing"
  | "updating"
  | "failed";
export type PluginCenterHealth = "ready" | "warning" | "failed" | "unknown";
export type PluginCenterAction = "install" | "update" | "enable" | "disable" | "remove" | "try_in_chat" | "manage";

export type PluginCenterCapability = {
  id: string;
  label: string;
  operation?: string;
  workflowStage?: string;
  agentSelectable?: boolean;
};

export type PluginCenterExtensionItem = {
  id: string;
  kind: PluginCenterKind;
  slug: string;
  name: string;
  summary: string;
  description?: string;
  icon: string;
  publisher: string;
  sourceId: string;
  sourceLabel: string;
  sourceType: PluginCenterSourceType;
  categoryIds: PluginCenterCategoryId[];
  tags: string[];
  featured: boolean;
  installed: boolean;
  enabled: boolean;
  installState: PluginCenterInstallState;
  installedVersion?: string;
  latestVersion?: string;
  updateAvailable?: boolean;
  requiresRunner?: boolean;
  serverId?: string;
  health: PluginCenterHealth;
  healthLabel: string;
  detailLabel?: string;
  manageHref?: string;
  primaryAction: PluginCenterAction;
  primaryActionLabel: string;
  actions: PluginCenterAction[];
  capabilities: PluginCenterCapability[];
  manifest?: Record<string, unknown>;
  tryInChat?: {
    enabled: boolean;
    promptTemplate?: string;
    capabilityId?: string;
  };
};

export type PluginCenterExtensionList = {
  schemaVersion: string;
  items: PluginCenterExtensionItem[];
  total: number;
  source: string;
  activeProfileId?: string;
  defaultProfileId?: string;
};

export type PluginCenterExtensionListResponse = {
  data: PluginCenterExtensionList;
};

export type PluginCenterTask = {
  id: string;
  kind: "remote-provisioning" | "tool-prepare";
  target: string;
  action: string;
  status: string;
  stage: string;
  message: string;
  createdAt: string;
  updatedAt: string;
  active: boolean;
  href?: string;
};

export type RemoteProvisioningJobAction = "ensure-runner" | "start-runner" | "upgrade-runner" | "repair-runner";
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
