# ADR: Draft Asset Run Boundary

Status: Accepted

Date: 2026-06-06

## Context

WorkflowDesignDraft and generated Snakemake workflow support are now past MVP shape. The next risk is not missing code volume; it is blurred ownership between editable workflow design, reproducible workflow assets, and execution facts.

Bio workflow platforms and adjacent standards draw this boundary clearly:

- GA4GH WES/TES separate workflow execution requests and task/run state.
- GA4GH TRS and Snakemake deployment patterns treat executable workflow/tool references as versioned assets.
- Workflow Run RO-Crate models a run as evidence over fixed workflow, data, and environment references.
- Galaxy tool XML and bio.tools/EDAM keep tool metadata and semantic classification separate from execution state.

The current project should keep the existing Windows launcher, local API facade, remote runner, and WorkflowDesignDraft investment. It should harden boundaries instead of restarting around a new runtime platform.

## Decision

Adopt this core lifecycle:

```text
WorkflowDesignDraft mutable design -> immutable asset revision -> run ledger facts
```

### WorkflowDesignDraft

WorkflowDesignDraft is the editable user design contract. It may be saved, reopened, validated, forked, and revised.

Drafts are not directly runnable. A run request must reference a compiled immutable asset revision, not caller-supplied draft content or ad hoc generated workflow content.

### Asset Revision

An asset revision is the immutable executable workflow bundle produced from a valid draft. It must include enough identity to reproduce and audit the run input:

- `pipeline.json`
- `Snakefile`
- workflow graph snapshot
- tool/profile/wrapper revision references
- dataset and resource references
- runtime lock and manifest references
- checksums for generated assets
- provenance metadata for compiler, source draft, and toolchain identity

Changing any of those inputs creates a new revision. Existing revisions are not mutated in place.

### Run Ledger

Run state belongs to `apps/remote_runner`. The remote runner owns the run state machine, append-only events, artifacts, cancel/retry effects, and SQLite ledger records.

`apps/api` and `core` must not keep shadow run state. They may expose typed query/control clients, UI-friendly aggregation, request validation, and forwarding. They must treat the remote runner as the source of truth for execution facts.

## Ownership Boundaries

`apps/web` owns editing, display, and interaction. It should move toward feature-owned slices such as `tools`, `workflows`, `workflow-design`, `databases`, and `remote-shell`.

`apps/api` is the local control-plane facade. It owns typed OpenAPI routes, request validation, local aggregation, and selected-runner routing. It does not duplicate remote run state.

`core` owns pure contracts, compilers, validators, typed remote clients, and reusable SSH/bootstrap/tunnel capabilities.

`apps/remote_runner` owns execution facts, run state, events, artifacts, registry persistence, and remote machine resource truth.

`config` owns declarative runtime, tool, profile, checksum, SBOM, provenance, and signature manifests.

`run.bat` remains the Windows development entrypoint. Its lifecycle should gain instance manifests, identity probes, version/build probes, layered health checks, and unified logs without bypassing the ownership boundaries above.

## Tool State

`qualityTier` must not become the only durable tool state field. Future persistent contracts should split state along these axes:

- `semanticState`: metadata/classification confidence and ontology fit.
- `runtimeState`: installability, environment lock, platform support, and runtime availability.
- `validationState`: rule spec, dry-run, smoke-run, output validation, and workflow-ready gates.
- `provenanceState`: source revision, checksum, SBOM, attestation, signature, and acceptance evidence.

UI may still present a rollup badge, but persisted contracts should keep the states separate.

## Runtime Strategy

Keep the current `conda-pack` plus explicit specs plus manifest approach for the near term. Add fail-loud validation, SBOM/provenance attestation, signatures, builder/source/toolchain hashes, and acceptance evidence before considering broader runtime replacement.

Do not introduce silent compatibility branches for unsupported older run shapes. Unsupported legacy payloads must fail clearly.

Container or Nix-style execution can be explored later as adapters. They should not be required for the next deliverable.

## Consequences

This decision narrows the next implementation work:

- Add a `service-info` contract for identity, version/build id, readiness, and state counts.
- Make asset revisions first-class and immutable before allowing draft-derived runs to depend on them.
- Move run history toward append-only events and auditable artifacts in `apps/remote_runner`.
- Keep React Query as the owner of frontend GET caching as features migrate into vertical slices.
- Keep React Flow as a possible view adapter only; domain graph contracts stay outside React Flow.

It also rejects these paths:

- Running mutable drafts directly.
- Maintaining run state copies in `apps/api` or `core`.
- Encoding all tool readiness and provenance into a single `qualityTier`.
- Adding broad backward-compatibility layers for removed generated workflow payload shapes.
