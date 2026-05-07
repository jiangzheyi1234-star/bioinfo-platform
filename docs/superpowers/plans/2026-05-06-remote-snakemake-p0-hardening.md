# Remote Snakemake P0 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make remote Snakemake deployment deterministic, fail fast when runtime is not ready, and promote a minimal operational smoke path for post-deploy verification.

**Architecture:** Centralize remote runner release metadata into one canonical manifest shared by Python and launcher code, tighten readiness enforcement at both host and remote submission layers, and expose the smallest bundled smoke path as a first-class operational entrypoint. Keep changes focused on control-plane/runtime orchestration and avoid unrelated frontend or database work.

**Tech Stack:** Python, FastAPI, Windows batch, PowerShell, SSH-managed remote runner, Snakemake runtime artifacts

---

### Task 1: Canonical Release Manifest And Bundle Lifecycle

**Files:**
- Create: `E:\code\bio_ui\config\remote-runner-release-manifest.json`
- Create: `E:\code\bio_ui\core\remote_runner\release_manifest.py`
- Modify: `E:\code\bio_ui\core\remote_runner\bundle.py`
- Modify: `E:\code\bio_ui\core\remote_runner\artifact.py`
- Modify: `E:\code\bio_ui\run.bat`
- Modify: `E:\code\bio_ui\scripts\deploy_remote_runner_artifact.py`

- [ ] Add one repo-owned manifest describing control-plane artifact name, workflow-runtime artifact name, versions, and relative search roots.
- [ ] Make Python artifact resolution load filenames and versions from the manifest instead of duplicating them in multiple modules.
- [ ] Make `run.bat` resolve both artifact paths from the same manifest rather than hardcoding separate filenames.
- [ ] Add `stop_service.sh` to the packaged remote runner bundle so stop/start/check lifecycle entrypoints are complete.
- [ ] Make the standalone deploy script fail loudly unless used in the intended narrowed scope, and stop presenting itself as a full cold-start bootstrap path.

**Acceptance:**
- One manifest file is the source of truth for artifact versions and filenames.
- The remote runner bundle contains `start_service.sh`, `stop_service.sh`, `check_service.sh`, and `launch_remote_runner.sh`.
- `run.bat` and Python artifact providers no longer hardcode artifact filenames independently.

### Task 2: Readiness Gate And Clear Failure Semantics

**Files:**
- Modify: `E:\code\bio_ui\core\app_runtime\service.py`
- Modify: `E:\code\bio_ui\core\remote_runner\manager.py`
- Modify: `E:\code\bio_ui\core\remote_runner\client.py`
- Modify: `E:\code\bio_ui\apps\remote_runner\main.py`
- Modify: `E:\code\bio_ui\apps\remote_runner\executor.py`

- [ ] Make host-side ensure/bootstrap require `ready.ok == true` before returning success.
- [ ] Preserve actionable workflow-runtime and pipeline-registry failure detail through host health responses.
- [ ] Add a remote-side synchronous submission gate in `/api/v1/runs` that rejects when workflow runtime or pipeline registry is not ready.
- [ ] Harden executor startup so missing Snakemake command, dry-run launch errors, and execution launch errors always transition the run to `failed` with explicit scope and message.

**Acceptance:**
- A runner that answers health but reports `ready.ok == false` is rejected before submission.
- Remote `/api/v1/runs` no longer accepts a run when workflow runtime inspection fails.
- Executor startup exceptions cannot leave accepted runs without a failed terminal state.

### Task 3: First-Class Operational Smoke Entry Points

**Files:**
- Create: `E:\code\bio_ui\scripts\remote_smoke.py`
- Create: `E:\code\bio_ui\scripts\remote_pipeline_smoke.py`
- Modify: `E:\code\bio_ui\skills\h2ometa-remote-smoke-test\scripts\remote_smoke.py`
- Modify: `E:\code\bio_ui\skills\h2ometa-remote-smoke-test\scripts\remote_pipeline_smoke.py`

- [ ] Add top-level wrapper scripts so the canonical smoke path is discoverable outside the skill bundle.
- [ ] Ensure the minimal smoke path is explicit: control-plane/bootstrap check first, then `file-summary-v1` end-to-end execution.
- [ ] Improve smoke failure output so operators get direct pointers to the next diagnostic step instead of generic failure text.

**Acceptance:**
- Operators can run `scripts\remote_smoke.py` and `scripts\remote_pipeline_smoke.py` from the repo root.
- The minimal smoke path remains `file-summary-v1` and is visible in script help and output.
- Smoke failures direct users toward health/log diagnostics instead of silent exit.

### Task 4: Integration Notes And Non-Test Verification

**Files:**
- Modify as needed within the task-owned files above only.

- [ ] Keep write scopes disjoint while implementing the three task groups in parallel.
- [ ] Run syntax-level verification only on touched Python files; do not run `pytest` from this environment.
- [ ] Summarize remaining manual validation steps for teammates who will run real remote tests.

**Acceptance:**
- All modified Python files compile successfully.
- Final handoff lists exactly which remote smoke steps teammates should run.
