import { requestLocalApiJson } from "@/app/lib/local-api-client";
import { cachedAsync, invalidateAsyncCache, invalidateAsyncCachePrefix, peekAsyncCache } from "@/app/lib/async-cache";

import {
  REMOTE_BROWSER_PAGE_SIZE,
  type DatabaseItem,
  type DatabaseTemplate,
  type DatabasesResponse,
  type DatabaseTemplatesResponse,
  type RemoteFilesResponse,
} from "./database-page-model";

type FetchOptions = {
  forceRefresh?: boolean;
};

const DATABASES_CACHE_KEY = "workflow:databases";
const DATABASE_TEMPLATES_CACHE_KEY = "databases:templates";
const DATABASES_CACHE_TTL_MS = 30_000;
const DATABASE_TEMPLATES_CACHE_TTL_MS = 60_000;

function refreshQuery(options: FetchOptions) {
  return options.forceRefresh ? "?refresh=true" : "";
}

export type BrowseRemoteFilesParams = {
  path: string;
  offset?: number;
  limit?: number;
  directoriesOnly?: boolean;
};

export type CreateDatabaseInput = {
  name: string;
  templateId: string;
  type: string;
  version: string;
  path: string;
  description: string;
  manifestPath: string;
  source: "manual";
  selectedEntryPath?: string;
  metadata: {
    templateId: string;
    selectedEntryPath?: string;
    input?: {
      kind: "multi";
      fields: Record<string, string>;
    };
    sourceUrl: string;
    buildCommand: string;
    dbParams: string;
    expectedFiles: string[];
  };
};

export type UpdateDatabaseInput = {
  name: string;
  version: string;
  description: string;
};

export async function fetchDatabases(options: FetchOptions = {}): Promise<DatabaseItem[]> {
  return cachedAsync(DATABASES_CACHE_KEY, DATABASES_CACHE_TTL_MS, async () => {
    const response = await requestLocalApiJson<DatabasesResponse>("GET", `/api/v1/databases${refreshQuery(options)}`, { cache: "no-store" });
    return response.data.items;
  }, {
    forceRefresh: options.forceRefresh,
  });
}

export async function fetchDatabaseTemplates(options: FetchOptions = {}): Promise<DatabaseTemplate[]> {
  return cachedAsync(DATABASE_TEMPLATES_CACHE_KEY, DATABASE_TEMPLATES_CACHE_TTL_MS, async () => {
    const response = await requestLocalApiJson<DatabaseTemplatesResponse>(
      "GET",
      `/api/v1/database-templates${refreshQuery(options)}`,
      { cache: "no-store" }
    );
    return response.data.items || [];
  }, {
    forceRefresh: options.forceRefresh,
  });
}

export function getCachedDatabases(): DatabaseItem[] | undefined {
  return peekAsyncCache<DatabaseItem[]>(DATABASES_CACHE_KEY);
}

export function getCachedDatabaseTemplates(): DatabaseTemplate[] | undefined {
  return peekAsyncCache<DatabaseTemplate[]>(DATABASE_TEMPLATES_CACHE_KEY);
}

export async function browseRemoteFiles({
  path,
  offset = 0,
  limit = REMOTE_BROWSER_PAGE_SIZE,
  directoriesOnly = false,
}: BrowseRemoteFilesParams): Promise<RemoteFilesResponse["data"]> {
  const response = await requestLocalApiJson<RemoteFilesResponse>(
    "GET",
    `/api/v1/ssh/files?path=${encodeURIComponent(path)}&directories_only=${directoriesOnly ? "true" : "false"}&limit=${limit}&offset=${offset}`,
    { cache: "no-store" }
  );
  return response.data;
}

export async function createDatabase(input: CreateDatabaseInput): Promise<DatabaseItem> {
  const response = await requestLocalApiJson<{ data: DatabaseItem }>("POST", "/api/v1/databases", {
    body: input,
  });
  invalidateDatabaseCaches();
  return response.data;
}

export async function checkDatabaseAvailability(id: string): Promise<DatabaseItem> {
  const response = await requestLocalApiJson<{ data: DatabaseItem }>(
    "POST",
    `/api/v1/databases/${encodeURIComponent(id)}/check`
  );
  invalidateAsyncCache(DATABASES_CACHE_KEY);
  return response.data;
}

export async function updateDatabaseRecord(id: string, input: UpdateDatabaseInput): Promise<DatabaseItem> {
  const response = await requestLocalApiJson<{ data: DatabaseItem }>(
    "PATCH",
    `/api/v1/databases/${encodeURIComponent(id)}`,
    { body: input }
  );
  invalidateDatabaseCaches();
  return response.data;
}

export async function deleteDatabase(id: string): Promise<void> {
  await requestLocalApiJson("DELETE", `/api/v1/databases/${encodeURIComponent(id)}`);
  invalidateDatabaseCaches();
}

export function invalidateDatabaseCaches() {
  invalidateAsyncCachePrefix("databases:");
  invalidateAsyncCache(DATABASES_CACHE_KEY);
}
