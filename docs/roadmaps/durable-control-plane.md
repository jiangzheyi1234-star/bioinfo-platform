# Durable Control Plane Roadmap

Status: Current

Last reviewed: 2026-06-09

This roadmap summarizes the current durable control-plane direction. The accepted decisions are `docs/adr/2026-06-06-draft-asset-run-boundary.md` and `docs/adr/2026-06-07-durable-control-plane-roadmap.md`; older long-form execution plans have been removed from `docs/` because they mixed completed work, proposed PR slices, and stale code paths.

## Boundary

H2OMeta uses this lifecycle:

```text
WorkflowDesignDraft mutable design -> WorkflowRevision immutable compiled workflow -> RunLedger facts
```

`WorkflowDesignDraft` remains editable. `WorkflowRevision` is the immutable compiled workflow identity used for run submission. Run state, events, attempts, leases, artifacts, and evidence belong to `apps/remote_runner`.

## Current Implemented Guardrails

- Shared WorkflowDesignDraft contract lives in `core/contracts/workflow_design.py`.
- Local API imports shared contracts instead of remote runner internals.
- Compile/export creates deterministic workflow revision records in `apps/remote_runner/workflow_revision_storage.py`.
- Draft-derived generated runs require `workflowDesign.draftId`, `workflowDesign.revision`, and `workflowRevisionId`.
- Remote runner storage includes run commands, append-only run event hashes, attempts, leases, candidate outputs, artifact materializations, and run-artifact edges.
- Release artifacts use manifest-declared bundles with digest, size, SBOM, provenance, attestation, builder, and source metadata.

## Next Priorities

1. Keep idempotent submission, attempt claiming, lease fencing, and candidate output adoption covered by focused tests.
2. Make workflow revision identity visible in the web UI wherever generated workflow submit readiness is shown.
3. Add UI smoke coverage for save -> validate -> compile -> submit on `generated-tool-run-v1`.
4. Continue moving frontend server-state surfaces toward generated API types when the OpenAPI client generation plan is ready.
5. Treat CWL, Nextflow, DRS, RO-Crate export, Kubernetes, Redis workers, and Postgres as adapters or later deployment modes, not prerequisites for the current SQLite remote runner model.
