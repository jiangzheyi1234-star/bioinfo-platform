import { expect, test } from "@playwright/test";

import {
  assertAgentPlanHash,
  canonicalAgentJson,
  sha256Hex,
} from "../../apps/web/app/components/agent-workbench-integrity";
import {
  requireAgentBudget,
  requireAgentSession,
  requireAgentSessionSnapshot,
  requirePositiveInteger,
} from "../../apps/web/app/components/agent-workbench-decode";
import type {
  AgentPlanRevision,
  AgentSession,
} from "../../apps/web/app/components/agent-workbench-model";

const PYTHON_CANONICAL_HASH = "1ee3dd9f65e12857cc58cdba8858fc30389d9f397db1b236aba249295d98c45b";

test("browser canonical plan hash matches the Python durable-store contract", async () => {
  const payload = {
    budget: {
      maxModelTurns: 1,
      maxToolCalls: 2,
      maxReplans: 0,
      maxRetries: 0,
      maxWallClockSeconds: 900,
    },
    contractVersion: "agent-plan-revision.v1",
    draftId: "draft_测试",
    draftRevision: 1,
    parentPlanRevisionId: null,
    planGeneration: 1,
    proposal: {
      draft: { nodes: [{ id: "fastqc", threads: 2 }], name: "质控" },
      planner: { adapterId: "fastq-qc" },
    },
    sessionId: "ags_fixture",
    validation: { orderedSteps: ["fastqc", "multiqc"], valid: true },
  };
  const canonicalPayload = canonicalAgentJson(payload);

  expect(await sha256Hex(canonicalPayload)).toBe(PYTHON_CANONICAL_HASH);
  await expect(
    assertAgentPlanHash(
      { ...payload, canonicalPayload, planHash: PYTHON_CANONICAL_HASH } as unknown as AgentPlanRevision
    )
  ).resolves.toBeUndefined();
  await expect(
    assertAgentPlanHash({
      ...payload,
      canonicalPayload,
      planHash: PYTHON_CANONICAL_HASH,
      validation: { ...payload.validation, valid: false },
    } as unknown as AgentPlanRevision)
  ).rejects.toThrow("AGENT_PLAN_CANONICAL_PAYLOAD_MISMATCH");
  await expect(
    assertAgentPlanHash({
      ...payload,
      canonicalPayload,
      planHash: "0".repeat(64),
    } as unknown as AgentPlanRevision)
  ).rejects.toThrow("AGENT_PLAN_CANONICAL_HASH_MISMATCH");

  const floatCanonicalPayload = canonicalPayload.replace('"threads":2', '"threads":2.0');
  await expect(
    assertAgentPlanHash({
      ...payload,
      canonicalPayload: floatCanonicalPayload,
      planHash: await sha256Hex(floatCanonicalPayload),
    } as unknown as AgentPlanRevision)
  ).resolves.toBeUndefined();
});

test("browser canonical plan integrity rejects unsafe integers without misclassifying booleans", async () => {
  expect(canonicalAgentJson({ enabled: true, disabled: false })).toBe(
    '{"disabled":false,"enabled":true}'
  );
  expect(() => canonicalAgentJson({ count: 9_007_199_254_740_993 })).toThrow(
    "AGENT_PLAN_CANONICAL_INTEGER_UNSAFE"
  );

  const unsafeCanonicalPayload =
    '{"budget":{"maxModelTurns":1,"maxReplans":0,"maxRetries":0,"maxToolCalls":2,"maxWallClockSeconds":900},"contractVersion":"agent-plan-revision.v1","draftId":"draft_unsafe","draftRevision":1,"parentPlanRevisionId":null,"planGeneration":1,"proposal":{"draft":{"nodes":[],"unsafe":9007199254740993},"planner":{"adapterId":"fixture"}},"sessionId":"ags_fixture","validation":{"valid":true}}';
  const parsed = JSON.parse(unsafeCanonicalPayload) as Record<string, unknown>;
  await expect(
    assertAgentPlanHash({
      ...parsed,
      canonicalPayload: unsafeCanonicalPayload,
      planHash: await sha256Hex(unsafeCanonicalPayload),
    } as unknown as AgentPlanRevision)
  ).rejects.toThrow("AGENT_PLAN_CANONICAL_INTEGER_UNSAFE");
});

test("agent decoders reject unsafe integers and non-exact atomic snapshots", () => {
  const code = "AGENT_FIXTURE_INVALID";
  const unsafeInteger = Number.MAX_SAFE_INTEGER + 1;
  const session: AgentSession = {
    contractVersion: "agent-session.v1",
    sessionId: "ags_fixture",
    projectId: "project-fixture",
    goal: { summary: "fixture", successCriteria: ["done"], context: {} },
    constraints: { allowedToolRevisionIds: [], forbiddenActions: [], requirements: {} },
    budget: {
      maxModelTurns: 1,
      maxToolCalls: 0,
      maxReplans: 0,
      maxRetries: 0,
      maxWallClockSeconds: 60,
    },
    status: "created",
    stateVersion: 1,
    planGeneration: 0,
    activeDraftId: null,
    activeDraftRevision: null,
    activePlanHash: null,
    workflowRevisionId: null,
    planner: { adapterId: null, adapterVersion: null, modelRef: null },
    lastErrorCode: "",
    creationRequestId: "create-fixture",
    createdBy: "fixture",
    createdAt: "2026-07-16T00:00:00Z",
    updatedAt: "2026-07-16T00:00:00Z",
    cancelledAt: null,
  };
  const snapshot = {
    contractVersion: "agent-session-snapshot.v1",
    session,
    events: [],
    plans: [],
    approvals: [],
  };

  expect(requireAgentSessionSnapshot(snapshot, code)).toEqual(snapshot);
  expect(() => requireAgentSessionSnapshot({ ...snapshot, serverId: "wrong-shape" }, code)).toThrow(
    code
  );
  expect(() => requireAgentSession({ ...session, stateVersion: unsafeInteger }, code)).toThrow(code);
  expect(() =>
    requireAgentSession({ ...session, activeDraftRevision: unsafeInteger }, code)
  ).toThrow(code);
  expect(() =>
    requireAgentBudget({ ...session.budget, maxToolCalls: unsafeInteger }, code)
  ).toThrow(code);
  expect(() => requirePositiveInteger(unsafeInteger, code)).toThrow(code);
});
