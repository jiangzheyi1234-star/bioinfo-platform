# WorkflowDesignDraft MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a persisted WorkflowDesignDraft layer that can save, reopen, validate, preview, compile, and submit only draft-derived Snakemake generated workflows.

**Architecture:** WorkflowDesignDraft v1 is the persisted design contract. The saved draft compiles into the existing generated workflow graph planner, which resolves saved registry tools, validates `workflowReady`, renders plan previews, and produces a draft-stamped runSpec. The public `generated-tool-run-v1` run path rejects direct generated runSpec shapes and accepts only saved draft-derived submissions.

**Tech Stack:** Python 3, FastAPI, Pydantic v2 strict models, SQLite remote runner registry, existing generated workflow planner/rendering modules, Next.js/React, Tailwind, shadcn/ui, TypeScript.

---

## Current Progress

- [x] Added strict `WorkflowDesignDraftV1` contract in `apps/remote_runner/workflow_design_contract.py`.
- [x] Draft input ids, input roles, node ids, normalized generated step ids, and exposed output aliases are unique and fail request validation on duplicates.
- [x] Added SQLite registry lifecycle in `apps/remote_runner/workflow_design_storage.py` and schema in `apps/remote_runner/storage_schema.py`.
- [x] Added remote runner and local API routes for create/list/get/update/fork/delete/plan/compile.
- [x] Local runtime plan/compile request bodies now fail before remote forwarding if anything besides the local `serverId` selector remains.
- [x] Added plan-only validation and preview in `apps/remote_runner/workflow_design_planner.py`.
- [x] Plan `normalizedGraph` and preview config `workflow.graph` now return the full normalized WorkflowDesignDraft contract, including metadata, inputs, resources metadata, output metadata, and provenance.
- [x] Added WorkflowDesignDraft plan-path graph validation coverage for invalid input roles, edges, and exposed outputs returning validation issues without runnable runSpecs.
- [x] Invalid plan responses for missing required database bindings now retain registry-derived `requiredResources` specs while keeping previews and runSpec empty.
- [x] Edge audit is now strict scalar design metadata; executable-looking nested audit payloads are rejected and audit is stripped from draft-derived generated runSpec edges.
- [x] WorkflowDesignDraft now rejects Python field-name aliases such as `from_`/`as_`, unknown edge audit scalar keys, and output aliases that collide after Snakemake target-name sanitization.
- [x] Added compile/export materialization in `apps/remote_runner/workflow_design_compiler.py`.
- [x] Aligned compiled `workflow/Snakefile` with the repo template contract by using runtime `run-config.json`, validating `workflow/schemas/config.schema.yaml`, and reading final outputs from `config["outputs"]`; `config/config.yaml` remains an exported example/config artifact.
- [x] Compile/export now clears previously generated `workflow/`, `config/`, `.test/`, and `README.md` outputs before materializing a fresh Snakemake project, while preserving unrelated files in the export root.
- [x] Compile/export now materializes through a staging directory and replaces generated export paths only after validation and asset writes succeed, so invalid drafts or asset conflicts cannot destroy a previous successful export.
- [x] Updated frontend generated workflow builder to save/reopen/validate/preview via WorkflowDesignDraft.
- [x] Reopen-and-save preserves existing WorkflowDesignDraft metadata/provenance where the graph identity is still valid, including top-level metadata, input metadata, node metadata/provenance, resource metadata, exposed output metadata, and non-exposed node output metadata for matching node id plus tool id.
- [x] Frontend edge recommendation audit is serialized into the scalar-only WorkflowDesignDraft audit contract with lossless JSON-string arrays; invalid or unknown persisted audit fields fail loudly on reopen instead of being silently dropped.
- [x] Changed generated run submission so `generated-tool-run-v1` requires `workflowDesign.draftId` and `workflowDesign.revision`.
- [x] Draft-derived run submission now rejects input role, filename, upload count, and unsupported input-field mismatches instead of accepting caller-mutated input bindings.
- [x] Frontend draft-derived submission now preserves planned input role and filename from the validated plan, attaching only upload IDs at submission time.
- [x] Ensured frontend uploads for draft-derived submissions use the selected runner `serverId`, so uploaded inputs, saved draft validation, and run creation target the same remote runner.
- [x] Added local selected-runner coverage for WorkflowDesignDraft create/update/fork so save, update, fork, list/load, plan/compile, upload, and run paths all preserve the local `serverId` selector while keeping remote payloads strict.
- [x] Ensured generated workflow remote smoke scripts use the selected runner `serverId` for upload creation as well as draft plan and run submission.
- [x] Removed live compatibility for request-side top-level `tool`, `workflow.steps`, graph-node `toolId`, and persisted/run payload `fromUpload`.
- [x] Removed the frontend builder acceptance path for persisted `{fromInput}` bindings as UI graph input; reopened drafts are converted to UI upload bindings explicitly, and unexpected persisted-shape input in the builder now fails.
- [x] WorkflowDesignDraft list/load errors and stale draft ids now surface visible errors instead of silently clearing to an empty draft list or no-oping.
- [x] Generated workflow submission now requires a visible valid plan for the current draft signature; edits to files, graph, resources, or opened draft identity clear stale plan/compile preview state before submission can proceed.
- [x] Current draft-build failures in the frontend are surfaced as WorkflowDesignDraft errors instead of being reduced to a silent null draft.
- [x] Added focused tests in `tests/test_workflow_design_drafts.py` plus updates to generated workflow, preflight, production-evidence, smoke-helper, and frontend structure tests.
- [x] Updated `docs/workflow-design-draft-v1.md` and `docs/snakemake-tool-integration-spec.md`.

## Remaining Verification Gates

- [x] Focused pytest passed from the current WSL2/Ubuntu Codex shell (128 passed on 2026-05-31; latest run `128 passed in 12.60s`):

```bash
unset UV_PYTHON
export PYTHONPATH=/mnt/e/code/bio_ui
export UV_CACHE_DIR=/mnt/e/code/bio_ui/.uv-cache-local
export UV_PROJECT_ENVIRONMENT=/tmp/bio_ui_codex_uv_venv_pytest
export UV_PYTHON_INSTALL_DIR=/mnt/e/code/bio_ui/.codex-uv-python
uv run pytest tests/test_workflow_design_drafts.py tests/test_workflow_design_compile_validation.py tests/test_workflow_design_plan_validation.py tests/test_workflow_design_resource_plan.py tests/test_workflow_design_local_api.py tests/test_workflows_page_structure.py tests/test_api_request_models.py tests/test_remote_runner_api_models.py tests/test_run_preflight_contract.py tests/test_generated_snakemake_smoke_payload.py tests/test_generated_runtime_overrides.py tests/test_generated_script_rules.py tests/test_generated_tool_output_semantics.py tests/test_generated_tool_snakemake.py tests/test_generated_wrapper_rules.py tests/test_tool_contract_pipeline.py tests/test_tool_contract_production_evidence.py -q
```

- [ ] User starts the browser UI from a real Windows shell and validates the user flow:

```bat
run.bat --web
```

Manual UI flow to check:

1. Open Workflows and select `generated-tool-run-v1`.
2. Add a workflow-ready tool node.
3. Bind at least one input and expose one output.
4. Click save/validate and confirm the plan preview shows Snakefile and config content.
5. Reopen the saved draft from the draft selector.
6. Submit a run and confirm the request uses the plan returned `workflowDesign.draftId` and `workflowDesign.revision`.
7. Confirm uploaded input requests include the same selected `serverId` as the final run submission.

## Completion Audit Snapshot

Current evidence supports code-level implementation for all seven MVP deliverables, and the focused WSL pytest gate has passed. The goal must stay active until the Windows launcher UI verification gate above is run from a real Windows shell.

| Requirement | Current evidence | Status |
| --- | --- | --- |
| Versioned `WorkflowDesignDraft v1` contract with nodes, edges, inputs, params, runtime, resources, outputs, metadata, provenance | `apps/remote_runner/workflow_design_contract.py`; strict create/update tests in `tests/test_workflow_design_drafts.py` | Implemented; pytest passed |
| Draft key ambiguity rejected loudly | `WorkflowDesignDraftV1` rejects duplicate input ids, input roles, node ids, normalized generated step ids, and output aliases; negative coverage in `tests/test_workflow_design_drafts.py` | Implemented; pytest passed |
| Public contract aliases and audit keys stay strict | `WorkflowDesignDraftV1` rejects `from_`/`as_`, unknown scalar audit keys, and Snakemake-safe output alias collisions; negative coverage in `tests/test_workflow_design_drafts.py` | Implemented; pytest passed |
| Remote runner registry lifecycle APIs create/list/get/update/fork/delete | `apps/remote_runner/workflow_design_storage.py`, `apps/remote_runner/workflow_design_routes.py`, local proxy in `apps/api/workflow_design_routes.py` and `core/app_runtime/runner_ops.py` | Implemented; pytest passed |
| Plan-only validation endpoint with normalized graph, ordered steps, resolved ports, resources/databases, exposed outputs, issues, Snakefile/config preview, no run creation | `apps/remote_runner/workflow_design_planner.py`; plan preview assertions in `tests/test_workflow_design_drafts.py`, including full normalized draft metadata/provenance; input/graph/output validation coverage in `tests/test_workflow_design_plan_validation.py`; missing database binding coverage in `tests/test_workflow_design_resource_plan.py` | Implemented; pytest passed |
| Compile/export boundary for standard Snakemake project layout | `apps/remote_runner/workflow_design_compiler.py`; compile route/client, layout, stale-generated-file cleanup, and invalid-draft export preservation assertions in tests | Implemented; pytest passed |
| Frontend save, reopen, validate through plan endpoint, preview before submission, compile action | `apps/web/app/components/workflow-design-draft-model.ts`, `workflows-page-api.ts`, `use-workflows-page-state.ts`, `generated-workflow-builder.tsx`; structure checks cover metadata/provenance preservation and visible draft load errors | Implemented; pending Windows `run.bat --web` UI verification |
| Draft-derived uploads target the selected runner | `apps/web/app/components/workflows-page-api.ts`; scoped structure assertions in `tests/test_workflows_page_structure.py`; local route coverage in `tests/test_workflow_design_local_api.py` | Implemented; pytest passed; pending UI verification |
| Focused tests/instructions for strict payload rejection, persistence, graph validation, plan preview, compile/export | `tests/test_workflow_design_drafts.py`, `tests/test_workflow_design_local_api.py`, `tests/test_workflows_page_structure.py`, `tests/test_api_request_models.py`, `tests/test_remote_runner_api_models.py` | Added; pytest passed |
| Docs with contract and next-phase roadmap | `docs/workflow-design-draft-v1.md`, `docs/snakemake-tool-integration-spec.md`, this plan | Implemented |
| No legacy compatibility or silent fallback | Planner/preflight reject top-level `tool`, request-side `workflow.steps`, graph node `toolId`, persisted/run `fromUpload`, caller `pipelineVersion`, and executable-looking edge audit; old direct shapes remain only in negative tests | Implemented; pytest passed |
| Saved tool contracts and `workflowReady` cannot be bypassed by AI-generated content | Draft stores `toolId` only; plan/compile resolves saved registry tools through `plan_generated_workflow_steps(require_workflow_ready=True)` | Implemented; pytest passed |

Allowed verification already run in this environment:

- Focused WSL pytest gate passed: `128 passed in 12.60s`.
- Python compile checks for touched API/remote/frontend-support tests.
- `npx tsc --noEmit --pretty false` in `apps/web`.
- Direct smoke for compile, custom-role submit, and strict stored runSpec.
- Direct check that WorkflowDesignDraft rejects `from_`/`as_`, unknown audit keys, and Snakemake-safe output alias collisions.
- Direct check that generated workflow submit gating requires a current visible valid plan and hides stale compile preview state.
- Direct check that frontend current draft-build failures are visible and not silently converted to null.
- Direct check that WorkflowDesignDraft plan/compile lifecycle API calls do not create run records.
- Direct check that WorkflowDesignDraft plan-path invalid input roles, edges, and exposed outputs return validation issues without previews or runSpecs.
- Direct check that missing required database bindings return an invalid non-runnable plan while preserving `requiredResources`.
- Direct smoke for local workflow design `serverId` routing.
- Direct check for local WorkflowDesignDraft create/update/fork selected-runner routing and remote-payload stripping.
- Direct check for local upload route preserving selected runner `serverId`.
- Scoped structure check proving `uploadWorkflowFile`, `submitWorkflowDesignRun`, and `submitPipelineWorkflowRun` preserve the selected runner `serverId`.
- Scoped structure check proving frontend reopen-and-save preserves draft metadata/provenance, rejects persisted `{fromInput}` as a UI builder input shape, and surfaces draft/server load errors visibly.
- Direct check that local runtime plan/compile requests strip `serverId`, reject unsupported fields before runner readiness or remote forwarding, and forward only empty plan/no-payload compile requests.
- Direct check that compile/export validation failures and script asset conflicts preserve previous generated export files instead of clearing them first.
- Direct check for compile/export cleanup removing stale generated files while preserving unrelated export-root files.
- Direct check that plan normalizedGraph/preview config return full draft metadata/provenance and that draft edge audit stays design-only.
- `git diff --check` passes except Git's CRLF/LF warning for `apps/remote_runner/pipelines/generated-tool-run-v1/pipeline.json`.

## Handoff Notes For Future Compaction

- Do not reintroduce old direct generated runSpec shapes. Keep legacy examples only as negative tests.
- Draft nodes persist `toolId`; generated runSpecs use canonical `workflow.nodes[].tool.id`.
- Draft node inputs persist only `{fromInput: role}`. Node-to-node dependencies live only in `edges`.
- Draft input ids, input roles, node ids, normalized generated step ids, and exposed output aliases must stay unique; do not add first-match behavior for duplicates.
- Plan/compile must resolve saved tool registry contracts and require `toolContract.workflowReady`.
- Public generated run preflight must reject caller `pipelineVersion`, including `null`.
- Draft-derived uploads must preserve the selected runner `serverId`; do not upload to the default runner and submit to another runner.
- Production evidence must read tool ids only from canonical `workflow.nodes[].tool.id`.
- Before marking this goal complete, perform a requirement-by-requirement audit against the original goal and use fresh verification evidence.
