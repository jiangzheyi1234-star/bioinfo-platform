# WorkflowDesignDraft v1

WorkflowDesignDraft is the persisted workflow design layer for user-composed Snakemake workflows. It is a versioned design contract, not an execution backend name. Snakemake remains the only compiler target in this MVP.

## Contract

Top-level payloads use `contractVersion: "workflow-design-draft-v1"` and `engine: "snakemake"`.

Required sections:

- `metadata`: `name`, `description`, `projectId`, and `tags`.
- `inputs`: named design inputs with `role`, preview `path`, optional `filename`, `mimeType`, and metadata.
- `nodes`: workflow graph nodes. Each node stores `id`, `toolId`, external `inputs`, `params`, `runtime`, `resources`, `outputs`, `metadata`, and `provenance`.
- `edges`: explicit node-to-node graph connections with `from.nodeId`, `from.port`, `to.nodeId`, and `to.port`.
- `resources`: database/resource bindings keyed by rule resource key.
- `outputs`: exposed workflow outputs with `from.nodeId`, `from.port`, and `as`.
- `provenance`: design-level provenance.

Node payloads intentionally store only `toolId`, not executable `ruleTemplate` or `ruleSpecDraft`. Node `inputs` bind external draft inputs by stable role with `fromInput`; positional upload bindings such as `fromUpload` are runtime/UI state and are not persisted in WorkflowDesignDraft. Upstream step bindings are represented by `edges`, so a saved DAG has one canonical source of truth for node-to-node links. Planning resolves the tool from the saved registry, validates `toolContract.workflowReady`, and uses the saved rule contract. AI-generated draft content cannot bypass saved tool contracts, ruleTemplate validation, or the workflow-ready gate.

The web builder converts persisted `{fromInput}` bindings into UI upload bindings only when reopening a saved draft. It does not accept persisted `{fromInput}` as an input shape while building a new draft from UI graph state. Reopen-and-save must preserve existing metadata and provenance for unchanged design identities, including top-level metadata, input metadata, node metadata/provenance, resource metadata, exposed output metadata, and non-exposed node output metadata when both node id and `toolId` still match.

UI edge recommendation audit may contain arrays for hard checks and evidence. At the WorkflowDesignDraft persistence boundary those arrays are encoded as scalar JSON strings, and only the known scalar audit keys `source`, `decision`, `confidence`, `reason`, `hardChecks`, and `evidence` are accepted on reopen. Invalid audit shapes fail loudly instead of being dropped.

All new API request models are strict Pydantic models with `extra="forbid"`. Public JSON must use the contract keys, including `from` and `as`; Python field-name aliases such as `from_` or `as_` are not accepted on API payloads. Unsupported older shapes must fail clearly. Do not add compatibility adapters for old generated workflow payloads.

Draft input ids, input roles, node ids, normalized generated step ids, exposed output aliases, and Snakemake-safe exposed output target aliases are unique within a draft. Duplicate values are rejected at request validation time so `fromInput` bindings, node references, generated step ids, and final output names never depend on list order or first-match behavior.

## APIs

Remote runner endpoints:

- `POST /api/v1/workflow-design-drafts`
- `GET /api/v1/workflow-design-drafts`
- `GET /api/v1/workflow-design-drafts/{draft_id}`
- `PATCH /api/v1/workflow-design-drafts/{draft_id}`
- `POST /api/v1/workflow-design-drafts/{draft_id}/fork`
- `DELETE /api/v1/workflow-design-drafts/{draft_id}`
- `POST /api/v1/workflow-design-drafts/{draft_id}/plan`
- `POST /api/v1/workflow-design-drafts/{draft_id}/compile`

The local API proxies the same routes for the web app through the existing remote runner manager.
Local plan/compile requests accept `serverId` only as a runner selector. After `serverId` is stripped, any remaining plan or compile body fields fail locally before the request is forwarded to the remote runner.

## Plan-Only Compiler

The plan endpoint validates a saved draft without creating a run. It returns:

- normalized draft graph
- topologically ordered steps
- resolved input/output ports
- required resources/databases
- exposed outputs
- validation issues
- Snakefile and config previews
- a draft-derived runSpec

The generated runSpec is derived from the saved draft plus current saved registry contracts. Valid plan responses stamp the runSpec with `workflowDesign.draftId` and `workflowDesign.revision`; invalid plan responses do not return a runnable runSpec. The web builder submits only after save plus plan validation, requires the visible plan to match the current draft shape, requires those draft markers, and attaches uploaded input IDs to that planned runSpec.

`normalizedGraph` and the preview config `workflow.graph` return the full normalized WorkflowDesignDraft contract, including metadata, inputs, node metadata/provenance, resources metadata, output metadata, and design provenance. Draft edge audit is design-only metadata: valid audit entries are scalar key/value pairs and remain in the normalized draft graph, but are stripped from executable generated runSpecs.

When a workflow-ready tool declares required database resources but the draft has not bound them yet, the plan response is invalid and non-runnable, but still returns the collected `requiredResources` specs. This gives the builder enough authoritative registry-derived information to prompt for missing resource bindings without accepting a fallback runSpec.

## Draft Registry

Draft records are stored in the remote runner SQLite registry with `draftId`, optional `parentDraftId`, `contractVersion`, `engine`, `name`, `projectId`, `revision`, timestamps, and the normalized draft JSON. Updates are optimistic through `expectedRevision`; conflicts fail with `WORKFLOW_DESIGN_REVISION_CONFLICT`. Forking creates a new draft at revision 1 and records the parent draft id. Older generated workflow request shapes are not adapted into registry records.

## Export Layout

The compiler/export boundary materializes:

- `workflow/Snakefile`
- `workflow/rules/generated.smk`
- `workflow/envs/*.yaml`
- `workflow/schemas/config.schema.yaml`
- `config/config.yaml`
- `README.md`
- `.test/run-config.json`

The exported `workflow/Snakefile` uses `configfile: "run-config.json"`, validates `workflow/schemas/config.schema.yaml`, and reads final target/output paths from `config["outputs"]`. `config/config.yaml` is a human-readable example/config artifact, while `.test/run-config.json` mirrors the runtime config shape used for dry-run validation.

## Current MVP Progress

- Added strict WorkflowDesignDraft v1 contract.
- Added SQLite persistence and lifecycle APIs.
- Added plan-only validation and preview.
- Returned full normalized draft graphs from plan/compile previews and kept design-only edge audit out of executable generated runSpecs.
- Invalid plan responses for missing required database bindings retain the registry-derived `requiredResources` specs while keeping previews and runSpec empty.
- Added compile/export materialization.
- Wired local API proxy routes.
- Updated the generated workflow builder to save, reopen, validate, preview, and submit through a planned draft runSpec.
- Preserved draft metadata/provenance on reopen-and-save and made draft/server load failures visible rather than treating them as empty draft lists.
- Stamped valid planned/compiled runSpecs with draft id and revision, and kept invalid plans non-runnable.

## Next-Phase Roadmap

1. Semantic Tool Recommendation v1: hard-filter tools by typed ports, EDAM data/format/operation, workflowReady state, and resource/database compatibility.
2. Run Orchestrator v1: rule-level Snakemake job status, cancellation, retry/resume, graph-projected logs, and persisted provenance/artifact lineage.
3. WorkflowDesignDraft revisions: explicit diff view, immutable revision snapshots, and promotion/export history.
