"use client";

import type {
  AgentCommandInput,
  CreateAgentSessionInput,
  DecideAgentPlanInput,
} from "./agent-workbench-api";

export type StoredAgentCommand =
  | {
      schemaVersion: "agent-workbench-pending-command.v1";
      kind: "create";
      serverId: string;
      sessionId: "new";
      body: CreateAgentSessionInput;
      storedAt: string;
    }
  | {
      schemaVersion: "agent-workbench-pending-command.v1";
      kind: "plan";
      serverId: string;
      sessionId: string;
      body: AgentCommandInput;
      storedAt: string;
    }
  | {
      schemaVersion: "agent-workbench-pending-command.v1";
      kind: "approve" | "request_changes";
      serverId: string;
      sessionId: string;
      body: DecideAgentPlanInput;
      storedAt: string;
    }
  | {
      schemaVersion: "agent-workbench-pending-command.v1";
      kind: "cancel";
      serverId: string;
      sessionId: string;
      body: AgentCommandInput & { reason?: string };
      storedAt: string;
    };

const PENDING_PREFIX = "h2ometa.agent.pending-command.v1";

export function pendingCommand(
  kind: StoredAgentCommand["kind"],
  serverId: string,
  sessionId: string,
  body: StoredAgentCommand["body"]
): StoredAgentCommand {
  return {
    schemaVersion: "agent-workbench-pending-command.v1",
    kind,
    serverId,
    sessionId: kind === "create" ? "new" : sessionId,
    body,
    storedAt: new Date().toISOString(),
  } as StoredAgentCommand;
}

export function storePending(command: StoredAgentCommand): void {
  if (!isStoredCommand(command, command.kind, command.serverId, command.sessionId)) {
    throw pendingStorageError("AGENT_PENDING_COMMAND_INVALID");
  }
  const key = commandKey(command);
  let serialized: string;
  try {
    serialized = JSON.stringify(command);
    window.localStorage.setItem(key, serialized);
    if (window.localStorage.getItem(key) !== serialized) {
      throw new Error("pending command write was not durable");
    }
  } catch {
    throw pendingStorageError("AGENT_PENDING_COMMAND_STORE_FAILED");
  }
}

export function clearPending(command: StoredAgentCommand): void {
  try {
    window.localStorage.removeItem(commandKey(command));
  } catch {
    // Best-effort local cleanup only.
  }
}

export function readPending(
  kind: StoredAgentCommand["kind"],
  serverId: string,
  sessionId: string
): StoredAgentCommand | null {
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(pendingKey(kind, serverId, sessionId));
  } catch {
    throw pendingStorageError("AGENT_PENDING_COMMAND_READ_FAILED");
  }
  if (!raw) return null;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    throw pendingStorageError("AGENT_PENDING_COMMAND_INVALID");
  }
  if (!isStoredCommand(value, kind, serverId, sessionId)) {
    throw pendingStorageError("AGENT_PENDING_COMMAND_INVALID");
  }
  return value;
}

function commandKey(command: StoredAgentCommand): string {
  return pendingKey(command.kind, command.serverId, command.sessionId);
}

function pendingKey(
  kind: StoredAgentCommand["kind"],
  serverId: string,
  sessionId: string
): string {
  return `${PENDING_PREFIX}:${encodeURIComponent(serverId)}:${encodeURIComponent(sessionId)}:${kind}`;
}

function isStoredCommand(
  value: unknown,
  kind: StoredAgentCommand["kind"],
  serverId: string,
  sessionId: string
): value is StoredAgentCommand {
  if (!isRecord(value) || !isRecord(value.body)) return false;
  if (
    value.schemaVersion !== "agent-workbench-pending-command.v1" ||
    value.kind !== kind ||
    value.serverId !== serverId ||
    value.sessionId !== sessionId ||
    !isNonemptyText(value.storedAt)
  ) {
    return false;
  }
  const body = value.body;
  if (body.serverId !== serverId) return false;
  if (kind === "create") {
    return (
      sessionId === "new" &&
      isNonemptyText(body.projectId) &&
      isNonemptyText(body.creationRequestId) &&
      isRecord(body.goal) &&
      isRecord(body.constraints) &&
      isRecord(body.budget)
    );
  }
  if (
    body.sessionId !== sessionId ||
    !isNonemptyText(body.requestId) ||
    !isNonemptyText(body.idempotencyKey) ||
    typeof body.expectedStateVersion !== "number" ||
    !Number.isSafeInteger(body.expectedStateVersion) ||
    body.expectedStateVersion < 1
  ) {
    return false;
  }
  if (kind === "approve" || kind === "request_changes") {
    return body.decision === kind && isNonemptyText(body.expectedPlanHash);
  }
  return kind === "plan" || kind === "cancel";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonemptyText(value: unknown): value is string {
  return typeof value === "string" && Boolean(value.trim());
}

function pendingStorageError(code: string): Error {
  const error = new Error(code);
  error.name = "AgentPendingStorageError";
  return error;
}
