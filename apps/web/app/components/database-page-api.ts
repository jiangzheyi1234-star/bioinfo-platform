import { requestLocalApiJson } from "@/app/lib/local-api-client";

import {
  REMOTE_BROWSER_PAGE_SIZE,
  type DatabaseItem,
  type DatabaseTemplate,
  type DatabasesResponse,
  type DatabaseTemplatesResponse,
  type RemoteFilesResponse,
} from "./database-page-model";

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

export async function fetchDatabases(): Promise<DatabaseItem[]> {
  const response = await requestLocalApiJson<DatabasesResponse>("GET", "/api/v1/databases", { cache: "no-store" });
  return response.data.items;
}

export async function fetchDatabaseTemplates(): Promise<DatabaseTemplate[]> {
  const response = await requestLocalApiJson<DatabaseTemplatesResponse>(
    "GET",
    "/api/v1/database-templates",
    { cache: "no-store" }
  );
  return response.data.items || [];
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
  return response.data;
}

export async function checkDatabaseAvailability(id: string): Promise<DatabaseItem> {
  const response = await requestLocalApiJson<{ data: DatabaseItem }>(
    "POST",
    `/api/v1/databases/${encodeURIComponent(id)}/check`
  );
  return response.data;
}

export async function updateDatabaseRecord(id: string, input: UpdateDatabaseInput): Promise<DatabaseItem> {
  const response = await requestLocalApiJson<{ data: DatabaseItem }>(
    "PATCH",
    `/api/v1/databases/${encodeURIComponent(id)}`,
    { body: input }
  );
  return response.data;
}

export async function deleteDatabase(id: string): Promise<void> {
  await requestLocalApiJson("DELETE", `/api/v1/databases/${encodeURIComponent(id)}`);
}
