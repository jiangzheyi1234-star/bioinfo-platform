# Generated Workflow Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Superseded by `docs/superpowers/plans/2026-05-30-workflow-design-draft-mvp.md`.

**Goal:** Make generated workflow preflight and rendering share one authoritative step-planning contract.

**Architecture:** Extract generated workflow request normalization, step ordering, tool contract resolution, input binding validation, and exposed output validation into a focused planning module. Keep rendering and file materialization in `generated_workflow.py`; keep `preflight.py` as a thin caller that translates planning `ValueError`s to `RunPreflightError`. This plan originally mentioned implicit direct single-tool request shapes; those are no longer valid. User-created `generated-tool-run-v1` requests must be derived from a saved WorkflowDesignDraft.

**Tech Stack:** Python 3, dataclasses, existing remote runner RuleSpec helpers, existing pytest coverage run by the user from WSL Codex CLI.

---

### Task 1: Shared Planning Contract

**Files:**
- Create: `apps/remote_runner/generated_workflow_plan.py`
- Modify: `apps/remote_runner/generated_workflow_graph.py`
- Modify: `apps/remote_runner/generated_workflow.py`
- Modify: `apps/remote_runner/preflight.py`
- Test: `tests/test_run_preflight_contract.py`

- [x] Replace direct single-tool payload support with strict rejection. User-created generated workflow runs require a saved WorkflowDesignDraft marker.
- [ ] Run the focused test from WSL Codex CLI only; in this Windows session do not run pytest.
- [ ] Move request step discovery, DAG ordering, tool lookup, workflow-ready checks, rule template resolution, param validation, input binding validation, and exposed output validation into `generated_workflow_plan.py`.
- [ ] Change `prepare_generated_tool_workflow` to consume planned steps instead of resolving tool contracts itself.
- [ ] Change `_preflight_generated_workflow` to call the shared planner and stop importing private helpers from `generated_workflow.py`.
- [x] Keep generated graph normalization aligned with the shared planner for canonical graph nodes, role-based inputs, and explicit exposed outputs. Request-side `toolId`, positional upload bindings, and legacy output aliases are unsupported.

### Task 2: Verification

**Files:**
- Modify: `tests/test_run_preflight_contract.py`
- Modify: `tests/test_generated_tool_snakemake.py` if import boundaries require it.

- [ ] Run allowed static checks only in this environment.
- [ ] Ask the user to run the focused Python pytest commands from WSL Codex CLI.
- [ ] Inspect `git diff --stat`, line counts for touched handwritten files, and local-only artifact leftovers before reporting completion.
