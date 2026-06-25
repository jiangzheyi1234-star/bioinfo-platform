# DAG Workflow Platform Maturity Roadmap

Status: In progress

Last reviewed: 2026-06-25

Baseline: `codex/dag-workflow-maturity-phase-2`, `HEAD=510efc863d54944e03a587cf963e08b9dc3881ee`.

Existing dirty files at intake: `AGENTS.md`. Treat this as pre-existing user/integrator work. Do not revert or overwrite it from this roadmap.

## Decision Card

Decision: Advance H2OMeta from a Snakemake-backed bioinformatics workflow builder toward a mature workflow platform through staged, reviewed slices. Do not attempt a broad rewrite or early multi-user production claim.

Track: architecture-track.

Why now: The current WorkflowDesignDraft, remote runner, artifact ledger, and release gates are strong enough to support the next platform layer, but the six requested capabilities cross frontend graph editing, semantic tool contracts, runtime telemetry, scheduling, artifact lifecycle, storage, and security governance.

Accepted constraints:

- `WorkflowDesignDraft` v1 remains a strict flat graph contract. Persisted node-to-node connectivity stays in `edges`; node inputs must not silently accept executable `fromStep` payloads.
- Snakemake remains the only compiler/execution target in the current MVP.
- User-facing graph upgrades must preserve the existing inspector/select binding fallback until drag/port connection behavior is proven.
- Runtime changes must respect attempt fencing, lease generation, candidate output adoption, and resource allocation invariants.
- Artifact lifecycle work must preserve content hashes and explicit manifest-declared outputs.
- Public multi-user server mode remains unsupported until identity, RBAC, audit, secret, database, and object-storage boundaries are implemented and tested.
- Windows owns launcher, frontend installs/builds, UI smoke, and Python quality gates when the Windows env is prepared.

Rejected alternatives:

- Do not replace the current builder with a new product surface in one pass.
- Do not add compatibility adapters for older workflow payloads.
- Do not add a login page before route-level authorization, audit, secret, and tenant/project storage boundaries exist.
- Do not implement custom Slurm scheduling primitives when official Snakemake executor/profile support can carry submit/status/cancel semantics.
- Do not hide unsupported storage, scheduler, or runtime behavior behind silent fallbacks.

Ownership split:

- Integrator owns this roadmap, phase sequencing, cross-slice contracts, final review, and cleanup.
- Frontend graph worker owns graph layout/history/canvas/port-connect UI under `apps/web/app/components/generated-workflow-*`.
- Semantic contract worker owns port compatibility, EDAM/resource scoring, and recommendation contracts under frontend model files, `core/contracts/rule_ports.py`, and capability graph tests.
- Runtime worker owns attempt/rule read models, Snakemake rule telemetry, run query APIs, and scheduler primitives under `apps/remote_runner`, `apps/api`, and `core/app_runtime`.
- Artifact worker owns storage adapter, lineage/cache/export/GC interfaces under `apps/remote_runner/artifact_*`, result preview/query, and result UI.
- Governance worker owns deployment/security/CI/release hardening under `core/deployment_mode.py`, `docs/security-governance.md`, `.github/workflows`, Docker/Compose, and diagnostics.
- Reviewer is read-only and checks phase order, hidden regressions, fallbacks, missing tests, and platform-rule violations before worker implementation.

Proof required:

- Focused pytest for each backend/runtime/storage/security slice.
- Frontend `npm run typecheck`, `npm run build`, and Playwright/UI smoke for graph interaction slices.
- Windows `run.bat --web` launcher smoke before claiming UI behavior stable.
- Real remote smoke gates only after reading `skills/h2ometa-remote-smoke-test/SKILL.md`.
- Release/security gates before claiming production handoff.

Stop conditions:

- A slice requires changing WorkflowDesignDraft v1 persistence semantics without a new contract decision.
- A runtime slice cannot preserve attempt fencing or candidate output adoption invariants.
- A storage slice cannot prove checksum preservation across adapter boundaries.
- A governance slice would expose remote file, SSH terminal, token rotation, or runner control to multi-user access without RBAC and audit.
- Windows/WSL environment ownership becomes ambiguous.

Cleanup: remove verification-only `.next`, `out`, Playwright traces/screenshots, `.pytest_cache`, temp Firecrawl files, and other local-only artifacts before final reporting.

## External Practice Anchors

- React Flow provides mature graph interactions: node dragging, zooming, panning, selection, handles, custom nodes/edges, subflows, save/restore, validation, and examples for ELK/dagre layout.
- Galaxy is the closest bioinformatics UX anchor: workflow editor, tool panel, details panel, compatible links, labeled outputs, workflow reports, workflow sharing, and subworkflow-safe output naming.
- EDAM is the domain ontology anchor for bioinformatics topics, operations, data, identifiers, and formats.
- CWL/WDL provide portable workflow-language anchors for typed inputs/outputs, subworkflows, scatter/backfill-like expansion, and explicit workflow/task boundaries.
- Prefect and Dagster provide scheduling/automation anchors: deployments, event triggers, work pools/workers, assets, sensors, partitions, and backfills.
- Argo Workflows provides DAG/runtime anchors: DAG task dependencies, retry strategy, CronWorkflow, artifact repository, TTL/GC, controller metrics, and workflow-level parallelism.
- Snakemake provides the execution anchor: rule DAG, resources, profiles, executor plugins, Apptainer software deployment method, persistence/provenance, reports, and between-workflow caching.
- OpenTelemetry semantic conventions provide observability naming anchors for logs, metrics, events, traces, and resources.
- OWASP ASVS, OWASP logging guidance, SLSA, GitHub secure Actions, CodeQL, Dependency Review, artifact attestations, and branch protection provide security/release anchors.

## Dependency Order

The six goals are not independent. The implementation order should be:

1. Contract and read-model foundations.
2. Frontend graph usability that does not alter persisted workflow semantics.
3. Semantic compatibility and recommendation scoring.
4. Rule-level runtime telemetry and normalized run detail.
5. Scheduler trigger model on top of stable run submission and provenance.
6. Artifact lifecycle and storage adapter expansion.
7. Production governance hardening and only then multi-user server work.

## Phase 0: Baseline Contracts And Review

Goal: make the platform direction executable without surprising existing workflow behavior.

Scope:

- Keep WorkflowDesignDraft v1 flat and strict.
- Document graph editor, semantic ports, runtime telemetry, scheduler, artifact lifecycle, and governance phase boundaries.
- Add contract tests where roadmap assumptions are not already protected.

Exit criteria:

- This roadmap is reviewed.
- Reviewer confirms no phase depends on silent fallback or unsupported multi-user exposure.
- First implementation slice is selected with a disjoint ownership boundary.

## Phase 1: Graph Editor Foundation

Purpose: upgrade the graph editor without changing the persisted contract.

Progress:

- Deterministic graph layout, undo/redo history, search, and graph viewport controls have landed.
- React Flow `@xyflow/react` is the selected graph editing surface for drag, pan, zoom, handles, edge deletion, minimap, and future subflow/group support.
- React Flow node positions now persist as scalar UI metadata (`uiPositionX`/`uiPositionY`) committed through graph history on drag stop and auto-layout; saved and compiled execution semantics remain unchanged.
- Direct canvas port connections now route through the same semantic compatibility and audit helpers used by inspector binding.
- Subflow grouping now uses editor node metadata (`uiSubflowId`/`uiSubflowLabel`) and display-only React Flow group nodes; the saved and compiled execution graph remains flat.
- Incompatible canvas port drops now reuse the shared one-hop converter recommendation policy used by the inspector, surface a stale-safe explicit confirmation prompt, and call the existing converter insertion path only after user confirmation.
- Workflow-ready tools can now be dragged from the palette onto the React Flow canvas. Drop coordinates are converted with the React Flow viewport transform and persisted only as scalar `uiPositionX`/`uiPositionY` metadata in the existing history model; execution graph semantics and edge inference remain unchanged.
- React Flow edge projection, handle-to-graph connection translation, and search matching now live behind a tested adapter module. Invalid canvas drops report explicit operator notices instead of silently doing nothing, and graph nodes/ports/handles expose stable non-visual selectors for future Playwright interaction proof.
- Selected graph nodes now expose deliberate subflow label controls with buffered assign, clear, and undo behavior. The UI still persists only scalar `uiSubflowId`/`uiSubflowLabel` metadata and renders display-only React Flow group overlays; it does not introduce nested WorkflowDesignDraft structure or React Flow parent-child persistence.

Recommended sequence:

1. Add pure graph layout helpers for deterministic topological layout.
2. Add local UI history helpers for undo/redo grouping.
3. Add viewport state for zoom/pan and search/highlight state.
4. Stop before port-handle connection behavior until Phase 2 has centralized compatibility tests. This prevents frontend/backend rule drift.
5. Add port-handle UI and connection validation only after the semantic compatibility baseline is shared by recommendations, inspector binding, and canvas interactions.
6. Evaluate React Flow plus ELK/dagre after pure contract tests land; if adopted, isolate it behind an internal graph adapter component.
7. Treat subflows initially as compiled WorkflowRevision-as-tool/templates, not nested WorkflowDesignDraft persistence.

Representative files:

- `apps/web/app/components/generated-workflow-graph-canvas.tsx`
- `apps/web/app/components/generated-workflow-graph-node-card.tsx`
- `apps/web/app/components/generated-workflow-builder.tsx`
- `apps/web/app/components/use-generated-workflow-builder.ts`
- New pure helpers such as `generated-workflow-graph-layout.ts`, `generated-workflow-history.ts`, and `generated-workflow-port-contract.ts`

Exit criteria:

- Existing save/validate/compile/submit flow still works.
- Graph nodes can be searched, highlighted, zoomed, panned, and auto-laid out.
- Undo/redo does not mutate compiled/exported identities unexpectedly.
- Port connection rejects incompatible links loudly and preserves edge audit metadata.

## Phase 2: Semantic Port System

Purpose: make tool composition explainable and domain-aware.

Progress:

- Centralized frontend/backend port compatibility now normalizes EDAM URI/CURIE values plus common bioinformatics data/format aliases such as FASTQ, SAM, BAM, TSV, JSON, sequence reads, and alignments.
- EDAM generic roots such as `data_0006` and `format_1915` are treated as weak compatible evidence, not hard conflicts and not automatic recommendation evidence.
- Recommendations and one-hop converter discovery now require stronger evidence than `type=file`; type-only and generic-only paths remain manual/ambiguous.
- Frontend local converter discovery now skips tools with database resource requirements, matching the backend capability graph converter filter.
- One-hop converter suggestions now carry machine-readable insertion guardrails: hard checks, evidence, `confirmationRequired`, explicit-user-confirmed insertion mode, auto-insertion blocked reasons, and visible “需确认，不会自动插入” UI copy.
- The semantic capability graph now exposes port operation/resource literals and database accepted-capability edges for better explainability.
- Canvas and inspector converter advice now share `generated-workflow-port-advice.ts`, so incompatible port drops can recommend the same workflow-ready/no-database/single-input/strong-evidence converter path without auto-mutating the graph.
- Incompatible canvas port drops now surface the same workflow-ready, no-database, strong-evidence one-hop converter advice as the inspector and require explicit confirmation before inserting a converter node; the former canvas-only `automatic-unambiguous` insertion path has been removed to keep backend plan recommendations authoritative.
- Capability bundles now preserve full semantic port metadata across API/frontend boundaries, including `operation` as advisory evidence and `resource` as hard compatibility evidence, so workflow recommendations and port audits do not lose EDAM/resource context after serialization.
- WorkflowDesignDraft external inputs now declare first-class `type`, `kind`, `data`, `format`, `operation`, and `resource` semantics. Plan/compile resolve those declarations into the same EDAM-aware hard compatibility gate used for step-to-step edges, while executable runSpec inputs remain file-binding payloads instead of carrying design-only port metadata.
- Frontend draft creation now preserves external input semantic fields when replacing upload files, and Python/TypeScript port compatibility share golden EDAM/resource/advisory parity cases so UI recommendations cannot drift from backend compile validation unnoticed.
- WorkflowDesignDraft plan responses now include a backend `semanticPortPlan` read model for every graph edge. It reports EDAM/resource compatibility decisions and one-hop converter candidates with hard checks, evidence, confirmation requirements, and no executable templates, paths, or automatic graph mutation.
- The workflow builder now renders the backend `semanticPortPlan` as the semantic edge diagnostics surface, including compatible/blocked edge counts, mismatch evidence, and converter candidates that map into the existing converter insertion path only after explicit user confirmation.
- Canvas and inspector converter insertion CTAs now require an exact backend `semanticPortPlan` candidate match for the source edge, target input, converter revision, and converter ports. Local TypeScript discovery remains visible only as a non-authoritative hint until the current draft has been saved and validated.

Recommended sequence:

1. Centralize port compatibility scoring as a pure function used by recommendations, connection validation, and tests.
2. Add EDAM-aware exact, alias, and known-compatible scoring for `data`, `format`, `operation`, and workflow stage metadata.
3. Add resource/database compatibility as a hard filter or visible blocker, not just UI decoration.
4. Keep recommendation audit scalar at the WorkflowDesignDraft boundary.
5. Add one-hop converter search: output -> converter -> target input.
6. Auto-insert converter nodes only after centralized tests prove a single unambiguous converter path and no target-input replacement risk.

Representative files:

- `apps/web/app/components/generated-workflow-port-contract.ts`
- `apps/web/app/components/generated-workflow-recommendation-contract.ts`
- `apps/web/app/components/generated-workflow-model.ts`
- `apps/web/app/components/workflows-page-api.ts`
- `core/contracts/rule_ports.py`
- `apps/api/bio_tool_pack_capability_graph.py`
- `apps/api/tool_profile_semantics.py`

Exit criteria:

- Incompatible EDAM/data/format links are blocked with an actionable reason.
- Recommendations include reason, confidence, hard checks, and resource compatibility.
- Converter insertion creates a normal WorkflowReady tool node and preserves existing graph invariants.

## Phase 3: Rule-Level Run View

Purpose: show every Snakemake rule/node status, logs, retry/resume context, and failure location.

Delivered foundation:

- Added fenced rule-state storage with `run_rules` and `run_rule_events`; rule publication requires the current `attemptId` and `leaseGeneration`.
- Added v2 SQLite migration coverage for the rule-level read model.
- Added remote/local `/api/v1/runs/{run_id}/rules` query path and included `rules` in run detail aggregation.
- Added executor projection from bundled manifest graph/generated workflow config into rule states, with success/failure updates per attempt.
- Added a Snakemake 9 logger-plugin event path (`--logger h2ometa`) that writes structured JSONL job events, then projects `JOB_INFO`, `JOB_STARTED`, `SHELLCMD`, `JOB_FINISHED`, and `JOB_ERROR` through the existing fenced rule-state storage.
- Structured Snakemake event projection now records rule command summaries, inputs, outputs, logs, wildcards, started/finished timestamps, and explicit `blocked`/`skipped` states for rules that did not reach a terminal job event.
- Added run detail `规则` tab plus DAG node status projection using `runtimeStatusKey`, then `stepId`, then `ruleName`.
- Added read-only run execution context projection for attempts, active/current lease, retry policy, retry eligibility, and explicit `resumeSupported: false`; surfaced it in run detail before enabling operator controls.
- Added live Snakemake logger JSONL polling during execution so structured rule events are incrementally projected while the workflow is running instead of only after process exit.
- Added strict whole-run operator retry: failed/canceled runs can be requeued through `POST /api/v1/runs/{run_id}/retry` with `scope: "run"`, preserving attempt id and lease-generation fencing while recording command, event, and governance audit evidence.
- Added a run detail retry action that is enabled only when the execution context reports `eligibleNow`; rule-level partial retry/resume remains unsupported instead of falling back silently.
- Added a read-only `ruleRetryPlan` contract to run execution context that computes failed-rule downstream invalidation/rerun scope from the immutable WorkflowRevision graph, selects the latest failed rule attempt for planning, and exposes cache/artifact adoption boundaries while keeping partial rule retry unsupported until execution semantics are safe.
- Added read-only failed-rule diagnostics in the run detail surface, grouping failed rule identity, attempt/lease, latest failure event, sanitized event details, stderr context, and managed log references without adding per-rule retry/resume actions.
- Snakemake engine adapter now has an internal rule-rerun command contract for future partial retry execution: explicit `--rerun-incomplete` plus `--forcerun <rule>` arguments are supported for dry-run/run commands, unsafe broad-force flags remain absent, and public retry API/UI stays whole-run only until output restoration and cache/artifact adoption are proven.
- Internal rule retry execution planning now maps a valid `ruleRetryPlan` to a blocked Snakemake options preview (`--rerun-incomplete --forcerun <selected failed rule>`), rejects missing selected attempts or unsafe rule names, preserves downstream invalidation scope for audit, and keeps `executionEnabled: false`.
- Run execution context and the run detail UI now expose the blocked `ruleRetryExecutionPlan`, including selected failed rules, downstream rerun scope, Snakemake args preview, prohibited unsafe flags, and cache/artifact/adoption blockers, while keeping rule-level mutation APIs and UI actions disabled.
- Run jobs now have a durable internal `executionOptions` contract that is persisted with queued retry intent, projected in execution context, carried through worker claim handling, and applied by the executor to Snakemake dry-run/run commands. Public rule-level mutation APIs remain disabled until output invalidation and adoption policies are proven.
- Added an internal fail-closed rule retry mutation seam: `request_rule_retry` refuses current disabled plans before mutation, materializes durable `run-job-execution-options.v1` only from `executionEnabled: true` rule plans, records command/event scope as `rule`, and keeps public API/UI rule retry disabled.
- Run execution context and the run detail UI now expose a read-only `resumePlan` preflight for failed/canceled terminal runs. It follows Snakemake `--rerun-incomplete` resume semantics, requires a WorkflowRevision, selects the latest resumable attempt for operator context, lists safe workdir evidence without paths, records incomplete-output audit and artifact-adoption blockers, lists unsafe flags, and keeps `executionEnabled: false` until workdir reuse and incomplete-output audit policies are proven.
- Resume preflight now performs a path-redacted latest-attempt output audit from managed `run-config.json` outputs, counting expected, present, missing, unsafe, unchecked, and unverified outputs without exposing filesystem paths; the mutation API remains disabled while workdir reuse/adoption policy is still blocked.
- Public rule-level retry and run resume routes now exist as confirmation-gated, plan-hash-fenced, fail-closed mutation APIs. They recompute the current plan, return the blocked plan with 409, record governance audit intent, and do not write retry commands, queue state, or execution options until output invalidation, workdir reuse, incomplete-output verification, and artifact/cache adoption contracts are proven.
- Rule retry execution planning now includes a side-effect-free `ruleCacheRestorePlan`/`cacheRestorePlan` preflight. It can preview per-rule cache keys and verified cache hits without writing lookup evidence, incrementing hit counts, creating pins, or exposing storage paths, while keeping restore execution blocked on per-rule cache eligibility, output-edge invalidation, staged-file policy, and partial-restore executor contracts.
- Rule retry execution context now includes a side-effect-free `ruleOutputInvalidationPlan` preflight. It maps the selected failed rule and downstream rerun scope to safe output artifact edges and lineage edge summaries, distinguishes preserved/unmatched outputs, exposes no paths or storage URIs, and keeps tombstone/delete mutation disabled until output and lineage invalidation policies are explicit.
- Run detail now includes a normalized `failureLocator` read model for failed runs, connecting the failed rule, latest failure event, stderr tail, related artifacts, and lineage edges. The fallback stderr projection also terminalizes non-failed rules as `blocked` instead of leaving stale `running` child states under a failed run.
- Failed-rule diagnostics now resolve rule log paths only through managed result artifacts and artifact preview APIs, expose capped rule-log tails when a matching log artifact exists, return explicit `PATH_REFERENCE_ONLY`/unavailable reason codes when only raw path references exist, and match durable lineage edges through `payload.artifactId`.
- Failure locator authority now lives behind governed remote/local `/api/v1/runs/{run_id}/failure-locator` read APIs with the frozen `run-failure-locator.v1` public contract. Local run detail consumes that remote contract instead of rebuilding failure diagnostics locally, and the public payload exposes safe counts, latest failed-rule identity, capped stderr/rule-log tails, redaction policy, and managed artifact summaries while excluding artifact paths, storage URIs, command summaries, run specs, and raw sensitive event details.
- The governed `/api/v1/runs/{run_id}/rules` read model now exposes `run-rules.v1` public rule evidence instead of raw storage rows. Operators see rule identity, attempt/lease, status, timings, exit code, sanitized event summaries, input/output/log reference counts, and managed log evidence/tails; raw rule input/output paths, log paths, storage URIs, and command summaries remain internal for execution, retry planning, and artifact export.
- `run-rules.v1` now includes a safe `run-rules-summary.v1` rollup and the run detail rule tab surfaces it before per-rule drilldown. The summary reports counts and status/log-evidence distributions only, keeping rule names, paths, storage URIs, command summaries, raw event details, and log lines out of the aggregate contract.
- Run attempts now have a stable read-only `run-attempts.v1` API that exposes job, attempt, lease, slot, retry, timeout, and summary state while explicitly redacting work directories, process identifiers, command payloads, and runSpec content. This makes attempt/lease evidence a standalone contract before any rule-level retry/resume mutation is enabled.
- Run observability read APIs are now governed high-risk remote actions. Run events, execution context, attempts, logs, rules, and failure locator require workflow-operator/auditor roles before storage or log reads and write hash-chained allow audit summaries with only counts, state distributions, stream labels, cursor-presence booleans, retry/resume eligibility flags, and log-evidence reason/status distributions, keeping log lines, rule-log tails, event detail payloads, run specs, command summaries, command args, paths, storage URIs, and raw cursor values out of governance audit details.

Still pending before this phase is complete:

- Add rule-level partial retry/resume mutation APIs only after rule-attempt selection, downstream invalidation, workdir reuse, incomplete-output audit, and cache/artifact adoption semantics are represented as explicit contracts.

Recommended sequence:

1. Expose stable attempt/slot/lease read APIs before adding new Snakemake telemetry.
2. Add rule telemetry tables/read models: `run_rules`, `run_rule_attempts`, `run_rule_events`, and rule log references.
3. Bind generated workflow `stepId/ruleName` and bundled manifest `runtimeStatusKey` to runtime rule states.
4. Select and pin a Snakemake structured event source or controlled wrapper before schema/API work depends on it.
5. Integrate that verified event source. Unsupported telemetry must fail visibly in the relevant feature path.
6. Require all rule events to carry `attemptId` and `leaseGeneration` so stale attempts cannot publish live rule state.
7. Add normalized run detail: run, attempts, rule states, events, logs, artifacts, lineage.
8. Add UI graph projection: node state badges, per-node logs, failed rule details, and retry/resume eligibility.

Representative files:

- `apps/remote_runner/storage_schema.py`
- `apps/remote_runner/workflow_run_storage.py`
- `apps/remote_runner/run_execution_storage.py`
- `apps/remote_runner/workflow_engine_adapter.py`
- `apps/remote_runner/executor.py`
- `apps/remote_runner/execution_query_storage.py`
- `apps/remote_runner/log_storage.py`
- `apps/api/execution_query_service.py`
- `apps/web/app/components/workflow-run-detail-panel.tsx`
- `apps/web/app/components/workflow-dag-preview.tsx`

Exit criteria:

- Successful and failing fixture workflows produce per-rule state transitions.
- Rule state publication is fenced by attempt id and lease generation.
- Retry attempts are distinguishable at rule level.
- UI can identify the failed rule, logs, inputs, outputs, wildcards, exit code, and command summary where available.

## Phase 4: Scheduler And Trigger Model

Purpose: support manual, cron, webhook/event, dataset/file/database-ready triggers, and backfill without bypassing run submission.

Progress:

- Manual and triggered run submission share the same durable run creation, admission, run job enqueue, and trigger provenance stamping path.
- Cron trigger definitions can now be evaluated by a remote-runner scheduler supervisor. Each due cron tick creates a stable immutable trigger event keyed by trigger id and scheduled UTC instant, then dispatches through the existing workflow trigger service.
- Cron tick replay is deduplicated by the existing trigger event and run idempotency stores; repeated scheduler evaluation for the same scheduled instant returns the existing event/run rather than creating another run.
- Webhook/event inbox ingestion now has a dedicated strict API route that requires `source` and `eventId`, keeps `correlationId` as grouping metadata, records an immutable trigger event envelope, and dispatches through the same workflow trigger service path.
- Dataset, file, and database-ready triggers now use a dedicated readiness push API. Trigger definitions must declare an explicit `triggerSpec.resource`, incoming ready events must match resource type/id/URI, and dispatch reuses the existing durable trigger event, idempotency, admission, run creation, run provenance, and governance audit path.
- Backfill triggers now support strict preview and confirmation-based launch APIs. Preview expands a half-open time range into deterministic partition windows, stable cursor/idempotency keys, concurrency estimates, and per-partition `runSpecPreview`; launch requires `confirmation: "launch-backfill"`, records durable launch/partition state, and dispatches admitted partitions through the same run creation, idempotency, provenance, and audit path as other triggers.
- Backfill launch now requires the deterministic `previewId` returned by preview and rejects mismatched launch payloads before creating launch or partition records, making preview-before-launch an explicit API contract instead of a caller convention.
- Backfill reprocessing behavior now follows the current explicit policy for each logical partition window: `none` skips any existing run, `failed` only creates a new run after a failed latest run, `completed` creates a new run after completed or failed latest runs, and queued/running partitions stay blocked from duplicate creation. Preview and launch expose `action`, `existingState`, `reprocessDecision`, skipped counts, and active-run blocking counts so operators can audit why each partition will create or skip a run.
- Generic `/events` launch remains closed for resource-ready sources and backfill partitions; dataset/file/database-ready dispatch must go through the readiness API, and backfill dispatch must go through the dedicated launch API.
- Backfill launch observability now exposes durable list/detail read APIs for launch state, partition summaries, linked trigger events, run ids, run status/stage, dispatch state, runSpec hashes, active run count, occupied slots, available slots, and concurrency-blocked partitions.
- Backfill admission now enforces per-launch `concurrencyLimit`: launch records all partitions durably, atomically claims only available pending partitions into admission, and the scheduler tick advances remaining pending partitions as earlier run slots reach terminal state.
- The web UI now has a read-only backfill launch surface under the run results area. It lists launches, summarizes partitions, links admitted partitions to their triggered runs, shows dispatch/run evidence and runSpec hashes, labels idempotent replays as existing-run reuse, surfaces reprocessing decisions for skipped partitions, and surfaces active/available/blocked concurrency state instead of exposing unsupported replay/dead-letter controls.
- The trigger/event observability read model and web UI now expose each submitted dispatch's linked run status, stage, and last update time next to the run link, while keeping dispatch state separate from run lifecycle state and still omitting raw payloads, runSpec JSON, create/enable/disable/pause/resume/replay/catchup/concurrency controls, and other unsupported scheduler operations.
- Trigger dispatch and backfill launch observability now expose each linked run's queue admission summary: job state, queue name, availability time, attempt budget, and allowlisted wait reason details for slot/resource contention. This keeps queue/resource waits visible without exposing raw `wait_reason_json`, worker slot identifiers, scheduler payloads, or adding unsupported queue control operations.
- Backfill launch cancellation now has an explicit confirmation-gated control path. It requests cancellation for non-terminal partition runs through the existing fenced run cancel command, marks pending/admitting partitions as `cancel_requested` so future scheduler ticks cannot submit them, records run-level and backfill-level governance audit evidence, and keeps replay/dead-letter/partial retry operations unsupported until their contracts are explicit.
- Webhook inbox submission now records provider-neutral inbound deliveries in a durable `workflow_trigger_inbox_events` table before dispatch, using `triggerId + source + eventId` dedupe, payload hashes, delivery counts, explicit `unsupported` signature state, linked trigger event/run ids, and `dead_lettered` failure state. The route still reuses the existing trigger event/dispatch path for run creation instead of creating a parallel scheduler.
- Dead-lettered webhook inbox deliveries now have a confirmation-gated backend replay path. Replay reconstructs the original inbound request from the stored inbox payload, requires the same trigger/event identity, re-dispatches the existing trigger event, repairs submitted inbox rows without creating duplicate runs, and records governance audit evidence.
- Internal webhook signature verification now has a pure provider contract for GitHub, Slack, and Stripe style HMAC signatures using raw request bodies, case-insensitive headers, timestamp tolerance for replay-prone providers, and secret-free verification results. It is intentionally not wired into inbox routes until secret provider storage and trigger signature policy are explicit.
- Webhook trigger signature policy now has a pure resolver that separates source labels from verification providers, requires `secretRef` for GitHub/Slack/Stripe HMAC policies, rejects inline secret-like fields and provider conflicts, exposes only secret-free policy details, and keeps generic provider-neutral inbox delivery marked `unsupported` until raw-request and secret-provider wiring are explicit.
- Webhook raw request handling now has a pure envelope contract that preserves the exact raw body bytes, normalizes headers without retaining signature values in safe details, parses only JSON object payloads for the existing inbox model, and proves future signature verification can avoid reserialized-body mismatches before route wiring changes.
- Workflow trigger create/list read models now redact `triggerSpec.secretRef` and other secret-like trigger fields while preserving raw internal storage for schedulers, readiness matching, backfill, and future verifier wiring.
- The webhook inbox FastAPI route now captures the raw request body, headers, and receipt time into the raw envelope before validating the existing inbox JSON payload, so later signature verification can use exact signed bytes while current storage still records `unsupported` signature state until verified metadata columns are added.
- Webhook inbox storage now persists safe raw request and signature audit metadata: raw body hash, raw body size, content type, header names, receipt time, and schema-tagged `signatureDetails`, while keeping `signatureState` as `unsupported` until secret-provider-backed verification is wired.
- Signed webhook inbox delivery now verifies required GitHub/Slack/Stripe-style policies from the raw envelope before JSON payload validation and dispatch when the trigger references an `env://` signing secret. Verified deliveries persist `signatureState: verified` and safe policy/credential/verification metadata; failed signatures are rejected before inbox persistence and do not create trigger events or runs.
- Webhook trigger creation now fails closed for known signed providers. GitHub, Slack, and Stripe trigger specs must declare an explicit signature policy and signing `secretRef` up front instead of accepting unsigned rows that only fail at delivery time.
- The local API webhook inbox proxy now preserves the original request body bytes and forwards only an allowlisted set of signature/event headers to the remote runner, so HMAC verification uses the same raw envelope through both local and remote entry points without leaking local Authorization, Cookie, or Host headers.
- Rejected signed webhook deliveries now record hash-chained governance deny audit evidence with safe raw-envelope metadata and provider/policy context, while still avoiding persisted inbox payloads, raw body bytes, signature header values, and secret references.
- Webhook trigger definitions now require an explicit `eventMatch` policy. Inbox delivery must match `triggerSpec.provider`, allowed event types, and optional action allowlists before any inbox row, trigger event, or run is created; no-match deliveries record safe governance deny audit evidence. The generic `/events` path no longer dispatches webhook triggers, and dead-letter inbox replay re-checks the current match policy instead of bypassing it.
- Dead-letter inbox replay now also re-checks the current signature policy. If a trigger has been upgraded to require signed delivery, only previously `verified` inbox rows can be replayed because raw request bodies are intentionally not stored for re-verification.
- The trigger observability UI now surfaces webhook inbox deliveries, delivery counts, signature state, safe raw request metadata, dead-letter failures, linked trigger events/runs, and confirmation-backed single-delivery replay, while keeping raw payload/body material and bulk replay controls out of the product surface.
- Dataset, file, and database-ready triggers now have an explicit opt-in readiness watcher supervisor. It polls configured local resource paths, records durable observation cursors, dispatches only changed ready versions through the existing readiness event path, and skips unchanged observations without creating replay audit noise.
- Database-ready triggers now also support an explicit `database_registry` readiness watcher adapter. It observes validated reference database registry records by stable non-path identity, dispatches only `available` database versions through the existing readiness event path, skips display-only/path relocation changes, and keeps raw database paths, manifest paths, source URLs, and path hashes out of readiness payloads.
- Readiness watcher observations now have a read-only API and trigger observability UI for dataset, file, and database-ready triggers. Operators can see observed/missing/error state, adapter, safe resource identity, version/checksum evidence, linked trigger event, and linked run without exposing raw resource URIs, local paths, or secret-bearing trigger spec fields.
- Cron trigger definitions now fail closed at creation time through a shared scheduler contract: trigger specs must declare one five-field cron expression, an explicit valid IANA timezone, and only an optional object payload; malformed legacy rows remain runtime-blocked without dispatch.
- Result package export evidence now records safe trigger provenance for triggered runs. The manifest, RO-Crate run action, and `result.export.v1` evidence link the run back to the immutable trigger event, dispatch request, optional webhook inbox delivery, and optional backfill partition/window without exporting raw trigger payloads, raw request bodies, signature header values, or secret references.
- Run detail now exposes the same safe trigger provenance read model used by result package export. Triggered runs show source, cursor, immutable trigger event, dispatch idempotency/request context, optional backfill partition window, and optional webhook inbox signature/raw-body hash metadata while keeping raw trigger payloads, request bodies, signature header values, and replay/dead-letter controls out of the run detail surface.
- Manual trigger definitions now have a confirmation-gated UI action that submits exactly one manual trigger event through the existing immutable trigger event, run admission, run creation, and provenance path. Cron catchup, webhook generic dispatch, readiness push, backfill launch, trigger creation, and pause/resume controls remain outside this observability surface.
- Workflow trigger scheduler ticks now persist safe hash-chained evidence and expose a governed read-only scheduler tick ledger in the trigger observability UI. The read model summarizes cron due/submitted/replayed/error counts and backfill submitted/pending/error counts without raw trigger payloads, run specs, event ids, run ids, cursor values, or scheduler controls.

Recommended sequence:

1. Keep manual submission as the base path.
2. Add trigger definition and trigger event models.
3. Add a scheduler service loop for cron and delayed enqueue using existing queue/admission semantics.
4. Add webhook/event inbox with deduplication, correlation id, actor/source, and idempotency key derivation.
5. Stamp triggered runs with `triggerId`, `triggerEventId`, `source`, and `cursor`.
6. Persist and govern scheduler tick summaries before adding scheduler controls or additional adapters.
7. Extend dataset/file/database-ready watcher polling from the opt-in local-path and database-registry adapters into additional explicit adapters only after each adapter has stable resource identity, version/checksum semantics, and cursor tests.
8. Extend backfill launch beyond explicit existing-run policy into replay/dead-letter/partial retry UI once their contracts are explicit.
9. Add provider signature adapters, event matching rules, replay/dead-letter UI, bulk replay controls, and rate-limit/retry policy after the provider-neutral inbox table proves stable.

Representative files:

- `apps/remote_runner/storage_schema.py`
- `apps/remote_runner/submission_service.py`
- `apps/remote_runner/run_execution_storage.py`
- New scheduler modules under `apps/remote_runner/`
- `apps/remote_runner/trigger_scheduler.py`
- `apps/remote_runner/trigger_scheduler_read_model.py`
- `apps/remote_runner/trigger_observability_governance.py`
- API routes under `apps/remote_runner` and `apps/api`
- Frontend workflow trigger views under `apps/web/app/components`

Exit criteria:

- Each trigger source creates an immutable trigger event and a deduplicated run submission.
- Backfill supports preview before launch.
- Queue admission, resource waits, and cancellation remain visible.
- Trigger provenance is visible in run detail and export evidence.

## Phase 5: Artifact, Lineage, Cache, And Export Lifecycle

Purpose: turn existing artifact ledger foundations into a production lifecycle.

Progress:

- Local artifact adapter is the default path for files and directories.
- File artifacts can now use the S3/MinIO-compatible adapter through the same persist, preview, checksum audit, export, materialization, evidence, and candidate adoption paths.
- S3/MinIO artifact keys are content-addressed by SHA-256 and use stable `s3://bucket/key` URIs; access keys and secret keys are excluded from public config and evidence.
- Directory artifacts on S3/MinIO now persist as a canonical H2OMeta BagIt-style directory package: the object key remains content-addressed by the logical directory SHA-256, the package records a deterministic manifest plus `data/` payload entries, S3 metadata stores package SHA/size, and preview, checksum audit, cache lookup, result export, and managed GC are package-aware.
- Artifact lifecycle state is now explicit on artifact and materialization rows. `/api/v1/artifacts/lifecycle/usage` reports active/deleted bytes and optional quota overage, `/gc/preview` produces a protected deletion plan, and `/gc/run` requires the `delete-artifact-payloads` confirmation before deleting managed local files or managed S3/MinIO objects.
- GC keeps metadata, lineage, and evidence append-only. It tombstones physical payload lifecycle state, writes `artifact.gc.v1` evidence, and records governance audit events.
- Current GC protection covers non-terminal runs, active jobs/leases/attempts, pending candidate outputs, exported result packages, production-evidence runs, active artifact-cache pins, unmanaged local paths, unmanaged S3 prefixes, unsupported storage backends, and unsupported local directory payload deletion. Managed S3/MinIO directory packages are collected as normal managed objects.
- Artifact cache indexing now records conservative exact cache keys only for managed WorkflowRevision-backed artifacts. Keys include workflow revision, artifact key, role/step, content digests for upload-backed inputs, and digests of params, resource bindings, and execution options. `/api/v1/artifacts/cache/entries` lists entries, and `/cache/lookup` verifies the referenced object is still inside managed artifact storage, exists, and matches size/SHA-256 before returning a hit.
- Artifact lineage now stamps `workflow_revision_id` for direct persist and candidate-adoption artifact publication, so cache and result audit surfaces can join a blob back to the immutable workflow contract.
- Upload-backed run inputs now register content-addressed input artifact blobs, local materializations, `run_artifact_edges(role=input)`, `prov:used` lineage edges, and `artifact.input.v1` evidence before workflow execution/cache adoption. Result packages surface those inputs as manifest `inputArtifacts` and Workflow Run RO-Crate `CreateAction.object` datasets without leaking local upload paths.
- Generated workflow run specs now support explicit artifact-backed inputs by `artifactId` or by `artifactBlobId` plus `materializationId`. The executor restores source payloads into the current run work input directory through the artifact adapter, verifies size/SHA-256, carries `upstreamRunId` and source materialization metadata into lineage/evidence/result packages, and keeps artifact cache keys content-addressed rather than source-ID-addressed.
- Fixed pipeline manifests now use the same explicit artifact-backed input contract as generated workflows: each input item must be exactly one of upload, `artifactId`, or `artifactBlobId` plus `materializationId`. The Workflows UI can select a completed run artifact as a pipeline input through a safe projection that submits only artifact id, role, and upstream run context while keeping paths, storage URIs, and cache keys out of client state and runSpec.
- Fixed pipeline artifact input selection now supports multiple artifacts across completed runs. The UI assigns roles from the fixed pipeline graph input order, preserves the selected artifact basket while browsing different source runs, de-duplicates selected artifacts, supports per-artifact removal, and still submits only safe artifact identifiers and provenance context.
- Fixed pipeline artifact baskets now include advisory artifact-to-role candidate ordering for the next target input role. The recommendation uses only safe artifact identifiers, kind, MIME type, size, checksum, and target role hints, never auto-selects an input, and leaves ambiguous candidates manual.
- File-summary fixed pipelines now keep their run-config schema and workflow scripts aligned with the explicit source contract: runtime inputs are source-neutral (`sourceType`/`sourceId`) and artifact inputs no longer fail because a workflow script assumes `uploadId`.
- Run/result detail read models now expose safe input artifact lineage (`inputArtifacts`/`inputArtifactCount`) from `prov:used` edges, and the run detail artifact tab surfaces upstream input blobs, ports, source type, source artifact id, upstream run id, size, MIME, and checksum prefix without exposing local paths or storage URIs.
- The run results list now joins the lightweight result read model to show output artifact and input lineage counts per terminal run, keeping detailed lineage payloads confined to the run detail surface.
- Cache lookup is traceable through `artifact.cache.lookup.v1` evidence and reports unmanaged cache objects as explicit misses instead of unavailable payloads. After a successful dry-run, the worker can now adopt a full set of cache-hit output artifacts into the current attempt only after rechecking the managed storage boundary, create attempt-scoped restore pins for the cached storage objects, restore the cached payload to each declared output path, write `artifact.cache.adopt.v1` evidence with cache pin IDs, record a local materialization, release restore pins, mark rules as cache-hit succeeded, and skip the expensive Snakemake run. Durable operator policy pins now expose retain/list/release API controls, optional expiry, artifact-curator RBAC actions, governance audit events, and GC protection for retained cache objects. Per-rule partial restore, downstream invalidation, and broader staged-file policy controls remain pending.
- Artifact cache read models now have a side-effect-free preview path for per-rule restore planning. The preview computes the same cache key and verifies managed payload/checksum state without recording cache lookup evidence or mutating cache hit counts, allowing run detail to explain cache hits/misses before any restore pins or staged-file changes are permitted.
- Artifact cache read APIs are now governed high-risk remote actions. Cache entry listing, cache pin listing, and cache lookup require artifact-curator/auditor machine-token roles, omit storage URIs from public responses, and write hash-chained allow/deny governance audit events using filter booleans, hit/miss state, and counts rather than raw workflow revision ids, cache selectors, storage URIs, or cache keys.
- Result package export is now a v2 evidence package rather than a bare artifact ZIP. Export requires a terminal run with a stored WorkflowRevision, passes checksum audit first, includes `manifest.json`, Workflow Run RO-Crate metadata, runSpec, WorkflowRevision, run events, rule states/events, lineage, evidence events, artifact checksums, and optional payload files. The temporary archive must pass package/metadata checksum and Workflow Run RO-Crate shape validation before `result.export.v1` evidence or a durable `result_package_exports` record is written.
- GC export protection is now exclusively metadata-backed through active result package export records for both full-payload and metadata-only exports. Deleting or moving the ZIP does not make exported artifact payloads eligible for collection; download paths still independently validate managed package location, active lifecycle state, size, and SHA-256.
- Run detail now exposes result package export controls that default to metadata-only packages, keep full-payload export explicit, and surface checksums, manifest hash, export evidence, and a backend-owned download affordance without exposing raw server filesystem paths.
- Result package exports now expose a safe browser download contract through `download.href` instead of raw server filesystem paths. The backend resolves downloads by `packageExportId`, cross-checks `resultId`, verifies the managed package root, active lifecycle state, size, and SHA-256 before streaming, and returns attachment/nosniff/no-store headers through the local API proxy.
- Result package exports now have confirmation-gated retire/tombstone controls. Retire verifies the active package record through the same managed-path, size, and SHA-256 checks used by download, marks the durable export record `retired`, blocks future downloads, releases GC `export_package` protection, and records `result.package.retire.v1` evidence plus governance audit without deleting the package ZIP or underlying run artifacts.
- Result package exports now have a lifecycle-aware inventory surface. Operators can rediscover active and retired export records after navigation, see checksums/provenance/payload mode, receive download affordances only for active records, and audit retired records without exposing raw server paths or inferring lifecycle from package ZIP presence.
- Retired result package exports now support an explicit, confirmation-gated package-byte deletion operation. The operation is single-export, managed-root-only, size/SHA-256 verified, RBAC governed, evidence/audit recorded, and keeps export metadata, lineage, and underlying run artifacts intact while marking `packageBytesState=deleted`.
- Run detail now exposes the result-package lifecycle as an operator product surface: active exports can be retired through the confirmation-gated route, retired exports with available package bytes can delete only the package ZIP bytes through the second confirmation-gated route, and download affordances are hidden unless both the export record is active and `packageBytesState=available`.
- Artifact lifecycle now has an explicit opt-in preview-only controller supervisor that evaluates TTL/quota policy, produces a GC preview plan, and records controller evidence/audit without deleting payloads or bypassing the explicit GC confirmation gate.
- Artifact lifecycle controller ticks now record a durable preview-only policy decision, retention-hold summary, batch-safety summary, and safe GC preview `planFingerprint`. The controller evidence and read model explain quota/TTL candidates, protected hold reasons, and `maxDeleteBytesPerTick` limiting without storing raw paths, storage URIs, group IDs, artifact IDs, run IDs, materialization IDs, or executing deletion.
- Result artifact preview and result package export audit now share a managed-storage gate before any payload read or export. Selected active artifacts must have complete metadata, point at a managed local result/work path or configured S3/MinIO artifact prefix, and pass live size/SHA-256 verification; corrupted local files, unmanaged paths/objects, symlinked local directory payloads, corrupted S3/MinIO directory packages, and unmanaged metadata-only exports are rejected with explicit audit/storage errors.
- Generic result read surfaces now return a governed public projection that preserves result IDs, artifact counts, checksums, lifecycle state, and input-lineage summaries while excluding result directories, local paths, storage URIs, package locations, and raw lineage edges from API payloads.
- Public result artifact projections now include a sanitized `artifactKey` output-port label derived from generated-artifact lineage when the label is slug-like and secret-free. Fixed-pipeline artifact input ranking uses that label as advisory evidence and the picker displays it, but selection remains manual and runSpec submission still sends only the explicit artifact source identity, role, and upstream run context.
- Artifact lifecycle usage reads are now governed high-risk remote actions. They require artifact-curator/auditor roles, fail before storage reads for wrong roles, and record hash-chained allow audit summaries with aggregate artifact counts, byte totals, and quota overage only, while excluding storage URIs, local paths, group ids, artifact ids, and run ids.
- Artifact GC preview/run routes now return public projections for operator/API responses and bind deletion execution to a stable preview `planFingerprint`. Internal GC plans and evidence keep deletion locators for auditability, but external payloads expose only plan ids, fingerprints, policy, counts, bytes, backend labels, retention reasons, and payload deletion booleans; storage URIs, local paths, group ids, artifact ids, run ids, materialization ids, and SHA-256 values stay internal. GC run fails closed with zero deletion when the caller omits a fingerprint or the current candidate/protection set no longer matches the preview.
- The artifact lifecycle UI now productizes the manual GC run path without enabling controller deletion: operators run only a saved preview, typed confirmation must match `delete-artifact-payloads`, the request reuses the saved preview policy plus `planFingerprint`, the stale preview is cleared after success, and the result surface shows only public counts, bytes, evidence id, backend labels, payload-deleted booleans, and stable error codes.
- Artifact cache governed reads now use public projections: cache entry/pin lists and lookup responses keep hit/miss reasons, evidence ids, lifecycle/checksum metadata, and digest-only fingerprints while excluding raw cache keys, key payloads, workflow revision ids, artifact/step selectors, and storage URIs from operator API payloads.

Recommended sequence:

1. Introduce a storage adapter interface and keep local adapter behavior first.
2. Extend result APIs to expose blob/materialization/edge/workflowRevision metadata.
3. Add artifact download/preview through adapters instead of direct local path reads.
4. Implement S3/MinIO-compatible adapter after local adapter tests pass. File artifacts and managed directory package artifacts are in place; raw multi-object directory trees remain intentionally unsupported.
5. Extend artifact-backed input selection from generated workflow specs into fixed pipeline manifests and UI selectors only after every caller declares one explicit source variant and rejects mixed upload/artifact references. Backend and Workflows UI support for multi-artifact fixed pipeline inputs, cross-run artifact baskets, and conservative advisory artifact-to-role ordering is now in place; future UX work should add richer semantic metadata to fixed pipeline input declarations before making recommendations more automatic.
6. Extend full-output cache adoption into per-rule restore only after per-rule cache eligibility, downstream invalidation, staged-file policy controls, restore pin creation, and partial-restore executor behavior are represented in run events.
7. Extend lifecycle from manual usage/preview/run into a background TTL/quota controller once durable package and cache-pin policies are finalized.
8. Extend explicit single-export result-package byte deletion into policy-driven quota/TTL planning only after operator UX, retention holds, and batch safety contracts are represented as durable evidence.

Representative files:

- `apps/remote_runner/artifact_storage.py`
- `apps/remote_runner/artifact_directory_package.py`
- `apps/remote_runner/artifact_ledger_storage.py`
- `apps/remote_runner/candidate_output_storage.py`
- `apps/remote_runner/execution_query_storage.py`
- `apps/remote_runner/result_preview_service.py`
- `apps/remote_runner/workflow_revision_storage.py`
- `apps/web/app/components/workflow-run-detail-panel.tsx`
- `apps/web/app/components/workflow-results-page.tsx`

Exit criteria:

- Local and S3/MinIO artifacts round-trip through the same API.
- Checksum audit detects corruption and blocks unsafe preview/export.
- GC never deletes active run, WorkflowRevision, production evidence, or export-protected artifacts.
- GC deletion is previewable, requires explicit confirmation, tombstones lifecycle state, and emits hash-chained evidence/audit records.
- Cache hit/miss is verified against live payload size and checksum before it is surfaced as reusable.
- Cache hit/miss is traceable and does not weaken reproducibility.
- Result package export requires a WorkflowRevision, includes provenance metadata and checksums, records durable export evidence, and protects exported payloads from GC by metadata record rather than filesystem presence alone.

## Phase 6: Production Governance

Purpose: harden supported deployment modes and prepare, but not fake, multi-user production.

Progress:

- Deployment mode selection now fails closed when `H2OMETA_DEPLOYMENT_MODE` is missing, blank, invalid, or set to the unimplemented multi-user mode. Supported launchers set `desktop` explicitly, and `server-single-user` API bind-all is rejected until an authenticated reverse-proxy/container profile is implemented and tested.
- High-risk local API and remote-runner API actions now have a machine-readable governance policy catalog that records the current supported boundary, future RBAC roles, audit subject/action, source route, and multi-user readiness. CI security governance audit checks policy validity, source route coverage, secret-safe audit detail keys, and implemented audit action evidence while keeping multi-user mode fail-closed.
- Remote-runner tool registry and reference database mutation paths now emit hash-chained governance audit events for create, prepare, cancel, rule-template update, production enable, delete, database create/update/check/delete, using metadata-only details that avoid command templates, manifests, package specs, database paths, and credentials.
- Security-sensitive automation now has CODEOWNERS coverage for workflow, Dependabot, and governance policy changes, and the CI security governance audit enforces pinned workflow actions plus safe workflow triggers. Dependency Review is now a PR-only `security / dependency-review` gate inside `required / ci-green`; CodeQL and OpenSSF Scorecard are wired as an independent, non-required `Security Analysis` workflow with SHA-pinned actions, least-privilege result-upload permissions, no untrusted PR upload trigger, SARIF/code-scanning output, and audit-enforced workflow contract checks until repository feature availability proves them safe to require.
- High-risk remote-runner actions now require explicit machine-token roles after bearer authentication. Missing or wrong roles fail with `RemoteRunnerAuthorizationError`, write deny governance audit evidence where the ledger is available, and cannot proceed to mutation, dispatch, retry, export, or GC work.
- Result package download is now a governed high-risk remote action (`result.package.download`) with artifact-curator/auditor role coverage and hash-chained audit evidence before the ZIP is streamed.
- Result artifact preview and checksum-audit reads are now governed high-risk remote actions (`result.artifact.preview` and `result.artifact_audit.read`) with artifact-curator/auditor role coverage. Successful reads record hash-chained allow audit events with result/artifact/checksum summaries but no preview content, while public preview/audit artifact metadata excludes paths, storage URIs, raw package locations, and tokens.
- Generic result read surfaces are now governed high-risk remote actions (`run.results.read`, `result.list`, and `result.read`) with artifact-curator/auditor role coverage. Successful reads record hash-chained allow audit events with subject ids plus count-only details, while public payloads exclude result directories, storage URIs, raw local paths, package paths, and raw lineage edges.
- Governance audit reads are now a governed high-risk remote action (`audit.events.read`) with auditor/platform-admin role coverage, so safe audit metadata remains queryable without exposing the audit trail to every authenticated runner token.
- Artifact cache read surfaces are now governed high-risk remote actions (`artifact.cache.entries.read`, `artifact.cache_pins.read`, and `artifact.cache.lookup`) with artifact-curator/auditor role coverage and safe allow audit summaries. The lower-level cache lookup evidence remains detailed for reproducibility, but operator governance audit entries do not copy raw workflow revision ids, cache selectors, storage URIs, or cache keys.
- Artifact lifecycle usage reads are now governed high-risk remote actions (`artifact.lifecycle.usage.read`) with artifact-curator/auditor role coverage and count/byte/quota-only audit summaries, keeping paths, storage URIs, lifecycle group ids, artifact ids, and run ids out of governance audit details.
- Artifact GC preview/run responses now use public lifecycle projections while the executor and evidence ledger retain raw deletion locators internally. GC run requires the current preview `planFingerprint` in addition to explicit delete confirmation, rejects stale plans before deletion, and failed delete responses return stable error codes instead of forwarding path-, object-, or digest-bearing exception strings to API clients. The web lifecycle action follows the same contract by binding execution to the saved preview instead of current form edits.
- Remote-runner secret references now have a pure provider contract for `env://`, `keyring://`, `secret://`, and `vault://` references that resolves only through an injected provider, exposes hash-only safe details, rejects inline/raw secret values, and backs signed webhook verification without exposing secret references in trigger read models, diagnostics, inbox metadata, or audit details.
- Remote-runner secret provider readiness now has a governed read API. It exposes only provider integration state, supported purposes, fail-closed unconfigured provider schemes, and redaction policy; it does not probe individual references, return raw refs, or claim `keyring://`, `secret://`, or `vault://` are wired before provider adapters exist.
- Webhook inbox replay is now a distinct governed remote action (`workflow_trigger.inbox_replay`) with workflow-operator role coverage, while replay dispatch reuses the existing trigger event and still records hash-chained replay audit evidence.
- Workflow trigger and backfill observability GET routes are now governed remote actions (`workflow_trigger.list`, `workflow_trigger.events.read`, `workflow_trigger.readiness_observation.read`, `workflow_trigger.inbox.read`, `workflow_trigger.backfill_launch.list`, and `workflow_trigger.backfill_launch.read`) with workflow-operator/auditor role coverage. Successful reads write hash-chained allow audit events with counts, filter-presence booleans, source/resource/state labels, and partition/run counters without copying payloads, cursor values, event IDs, payload hashes, raw resource URIs, run specs, or storage paths.
- CI security governance audit now models GitHub Actions workflow permissions, rejects unversioned external actions and privileged follow-up triggers, caps `actions/upload-artifact` retention at 2 days for handoff/debug files, and allowlists only the explicit release-attestation and release-publishing write scopes needed by current workflows.
- GitHub Actions checkout steps now set `persist-credentials: false`, and the CI security governance audit rejects future checkout steps that would leave `github.token` credentials in local git config.
- Dependabot version updates now cover GitHub Actions, root `uv`, root npm, `apps/web` npm, and `apps/desktop` npm surfaces with weekly grouped updates and a five-open-PR cap. The security governance audit rejects missing, unapproved, or noisy Dependabot entries so dependency upkeep remains part of the production gate instead of an ad hoc operator task.
- The desired GitHub main-branch ruleset is now source-controlled as `.github/rulesets/main-branch-ruleset.target.json` and enforced by the security governance audit as a target policy: no bypass actors, PR/code-owner/review-thread gates, linear history, deletion/force-push protection, and only the stable `required / ci-green` aggregate as a required status check until optional Security Analysis gates are proven available.
- Container image scanning is now source-controlled as `.github/container-image-scan.target.json` plus an independent, non-required `.github/workflows/container-image-scan.yml` workflow. The workflow builds both Dockerfiles, runs pinned Trivy scans for HIGH/CRITICAL OS/library vulnerabilities, uploads two-day SARIF evidence, and stays out of `required / ci-green` until the unsupported Compose draft is replaced by a hardened server profile.
- Workflow trigger scheduler tick reads are now governed remote actions (`workflow_trigger.scheduler_ticks.read`) with workflow-operator/auditor role coverage and metadata-only allow audit records. Public scheduler evidence includes only aggregate cron/backfill counts, error type/reason-code counts, evidence ids, and timestamps; trigger payloads, event ids, run ids, run specs, cursor values, and scheduler controls remain unavailable.
- Remote runner database backend configuration now fails closed. The supported backend is explicitly `sqlite`; `database_backend=postgres` and `H2OMETA_DATABASE_URL`/`database_url` are rejected before runtime layout or storage connection can silently initialize SQLite, keeping PostgreSQL marked as pending until repository, transaction, migration, and multi-user governance boundaries are implemented.
- Governance audit events now expose stable request, correlation, project, and tenant context fields in the hash-chained audit payload/read model. Context is promoted from existing safe details such as run submission `requestId`/`projectId` and trigger `eventContext.correlationId`, while raw details remain secret-key guarded.
- Governance audit events now expose stable top-level `actorRoles` from the authenticated remote-runner machine token, including authorization denials. Roles are not promoted from lower-trust business/event details, and this remains a machine-token boundary rather than per-user multi-tenant RBAC.
- Governance audit reads now record their own hash-chained `decision=allow` event after RBAC succeeds. The event captures actor roles, filter-presence booleans, requested limit, and returned count while deliberately excluding raw query filter values so an operator cannot accidentally copy a token or secret into the audit ledger through the read API.
- Run observability reads are now governed remote actions (`run.events.read`, `run.execution_context.read`, `run.attempts.read`, `run.logs.read`, `run.rules.read`, and `run.failure_locator.read`) with workflow-operator/auditor role coverage and metadata-only allow audit records. Logs, failure-locator tails, event detail payloads, run specs, command summaries, command args, local paths, artifact paths, storage URIs, and cursor values are excluded from governance audit details.

Recommended sequence:

1. Preserve current supported boundary: desktop/local single-user plus authenticated remote runner.
2. Make unsupported public multi-user selection fail closed until identity, RBAC, audit, tenant/project, storage, and secret boundaries exist.
3. Make invalid deployment-mode values fail loudly instead of silently selecting desktop behavior.
4. Harden single-user server/Compose only after localhost/reverse proxy, non-root containers, secret mounts, resource limits, TLS/proxy guidance, and image scanning are ready.
5. Add identity/session, RBAC policy matrix, project/tenant model, audit event schema, and secret provider interface before enabling server multi-user.
6. Add Postgres only after repository/transaction boundaries are clear.
7. Add S3/MinIO storage only through the artifact adapter layer.
8. Add CodeQL, Scorecard, image scanning, branch protection/ruleset, release attestations, and RC evidence gates.

Representative files:

- `core/deployment_mode.py`
- `docs/security-governance.md`
- `docs/deployment-modes.md`
- `.github/workflows/ci.yml`
- `.github/workflows/release-remote-runner-artifacts.yml`
- `.github/workflows/promote-remote-runner-release.yml`
- `Dockerfile.api`
- `Dockerfile.web`
- `docker-compose.yml`
- `scripts/verify_release_candidate.ps1`
- `scripts/security_governance_audit.py`

Exit criteria:

- Public multi-user mode cannot be selected accidentally.
- Auth/RBAC tests cover allow/deny for high-risk routes.
- Audit logs include actor, machine-token actorRoles, tenant/project context where available, action, target, outcome/decision, request/correlation ids, and tamper evidence.
- Secrets are never returned by diagnostics or logs.
- Postgres migration and S3/MinIO artifact round-trip tests pass before multi-user beta.
- CI and release gates produce repeatable evidence.

## Reviewer Checklist

- Does the phase order preserve current MVP behavior?
- Are all new fallbacks explicit, visible, and tested?
- Are cross-cutting contracts updated before dependent UI/runtime code?
- Does every high-risk route have an eventual auth/RBAC/audit owner?
- Does every storage move preserve checksum, lineage, and reproducibility?
- Are Windows and WSL ownership rules respected?
- Are local-only artifacts cleaned after proof?
