# ADR: Durable Control Plane Roadmap

Status: Accepted

Date: 2026-06-07

## Context

The accepted boundary ADR in `docs/adr/2026-06-06-draft-asset-run-boundary.md` defines the core lifecycle:

```text
Draft -> WorkflowRevision -> RunLedger
```

H2OMeta now needs the first durable control-plane guardrails around that lifecycle before larger executor, schema, and frontend changes. The current system already has WorkflowDesignDraft contracts, Snakemake execution, remote runner storage, run events, tool preparation, and a local API facade. The remaining risk is that mutable draft state, executable assets, run facts, and runner process effects can still be advanced by command-style paths without a durable asset revision, queue, attempt, or lease boundary.

## Decision

Adopt a phased durable control-plane roadmap where the remote runner is the source of truth for run facts, workflow revision identity, event ledgers, execution attempts, leases, artifacts, and evidence. `apps/api` and `core` may route, validate, aggregate, and expose typed clients, but they must not keep shadow run state.

The first three durable tables to add are:

- `run_attempts`
- `run_leases`
- `workflow_revisions`

The first implementation sequence is:

1. Add architecture guardrails and contract boundary tests.
2. Harden idempotent submission so duplicate requests cannot enqueue or start duplicate execution.
3. Add durable run jobs, attempts, leases, and fencing generations.
4. Move run events toward a versioned append-only event appender.
5. Add resource envelope tables and a shadow reconciler before replacing existing behavior.

## Boundaries

Workflow drafts stay mutable and user-editable. Runs must execute immutable workflow revisions, not mutable drafts and not caller-supplied executable workflow bodies.

Workflow revisions are immutable compiled workflow records. They must include generated workflow files, graph snapshots, tool and wrapper revision references, runtime lock identity, resource references, checksums, and compiler provenance. Any material change creates a new workflow revision. The term asset is reserved for data assets, artifact blobs, database versions, and future DRS or RO-Crate objects.

Run ledger facts belong to `apps/remote_runner`. Runs, jobs, attempts, leases, events, artifacts, cancel/retry facts, evidence, and reconciliation observations are remote-runner-owned state.

Execution fencing must protect both database writes and the filesystem. Every attempt writes into an attempt-scoped working directory, terminal publication is atomic and gated by the current lease generation, and expired attempt process groups must be stopped before a replacement attempt can publish.

Output recovery must follow `candidate_outputs -> verify -> adopt`. Fenced or crashed attempts may record candidate output paths and checksums, but only verified candidates can become official artifacts.

Resource envelopes must include finalizers, deletion timestamps, owner references, and conditions from the first version. Reconcile work must be deduplicated and use bounded exponential backoff with jitter so a failing item cannot busy-loop.

Artifact lineage should be modeled as a run-artifact bipartite graph. `artifact_materializations` include `storage_backend` and `storage_uri`; `run_artifact_edges` connect runs to artifact blobs with role, port, step, content hash, and optional denormalized upstream run id.

## Non-Goals For The First 90 Days

The roadmap rejects Kubernetes, Temporal, mandatory Redis, Argo, Nextflow, CWL, and a new engine-independent workflow DSL as required platform dependencies for the first 90 days.

Redis-backed workers, Kubernetes-native execution, CWL/Nextflow export, Postgres deployment mode, DRS, and RO-Crate export can be evaluated later as adapters or export surfaces after the SQLite durable runner model is proven.

## Legacy Payload Policy

old ad hoc executable run payloads must fail loudly once v2 submit is enabled. The system must not add silent fallback paths that execute caller-supplied RuleSpec, mutable draft content, or legacy generated workflow bodies to preserve older behavior.

Unsupported payloads should return clear problem details that name the unsupported contract and the required asset revision submission path.

## Consequences

This decision makes Phase 0 a guardrail phase, not a platform rewrite. Schema, executor, and frontend work should land behind tests that preserve the Draft -> WorkflowRevision -> RunLedger boundary.

The near-term implementation should remain compatible with FastAPI, SQLite, Snakemake, Next.js, Tailwind, shadcn/ui, the Windows launcher, and the current remote runner process model while progressively adding durable jobs, attempts, leases, events, workflow revisions, artifacts, and reconciliation.
