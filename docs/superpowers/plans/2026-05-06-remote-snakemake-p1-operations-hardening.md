# Remote Snakemake P1 Operations Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add post-bootstrap canary validation, rollback-safe release switching, and managed Snakemake workflow-profile assets to the remote runner path.

**Architecture:** Keep `core.remote_runner.manager` as the control-plane authority for release orchestration and remote runtime provisioning. Add one managed workflow-profile directory under the remote shared config root, teach the remote executor to consume it by default, and make bootstrap persist enough release metadata to support automatic canary execution and rollback on failed upgrade. Keep the Local API contract thin by surfacing the new metadata through existing ensure-runner and server-health payloads instead of reviving removed environment-management routes.

**Tech Stack:** Python, FastAPI, remote SSH orchestration, Snakemake 9 workflow profiles, JSON config/state files

---

### Task 1: Persist Managed Workflow Profile Assets

**Files:**
- Modify: `E:\code\bio_ui\core\remote_runner\manager.py`
- Modify: `E:\code\bio_ui\apps\remote_runner\config.py`
- Modify: `E:\code\bio_ui\apps\remote_runner\main.py`
- Modify: `E:\code\bio_ui\apps\remote_runner\executor.py`

- [ ] Add managed workflow-profile fields to the remote runner config payload and dataclass.
- [ ] Write a repo-owned profile YAML into the remote shared config tree during bootstrap.
- [ ] Extend readiness so `/health/ready` verifies the configured profile path exists.
- [ ] Update Snakemake execution to pass `--workflow-profile` and let the profile carry default execution flags.

### Task 2: Add Bootstrap Canary Execution

**Files:**
- Modify: `E:\code\bio_ui\core\remote_runner\manager.py`
- Modify: `E:\code\bio_ui\core\remote_runner\client.py`
- Modify: `E:\code\bio_ui\core\app_runtime\service.py`

- [ ] Add a small manager-owned canary helper that uploads a tiny FASTQ payload and submits `file-summary-v1`.
- [ ] Poll the run to terminal state and capture artifact/preview evidence in bootstrap metadata.
- [ ] Surface canary outcome through the existing ensure-runner response/registry snapshot.
- [ ] Fail bootstrap loudly if the canary does not complete successfully.

### Task 3: Add Rollback-Safe Release Switching

**Files:**
- Modify: `E:\code\bio_ui\core\remote_runner\manager.py`
- Modify: `E:\code\bio_ui\core\app_runtime\runner_ops.py`

- [ ] Record the previously active release before switching `current`.
- [ ] If startup, readiness, or canary fails after switching, restore the previous release and restart it with the preserved mode.
- [ ] Persist rollback outcome in bootstrap metadata so operators can see whether rollback was attempted or completed.
- [ ] Keep stop-service behavior compatible with both current and previous release layouts.

### Task 4: Update Focused Tests and Operator Docs

**Files:**
- Modify: `E:\code\bio_ui\tests\test_remote_runner_api_lifecycle.py`
- Modify: `E:\code\bio_ui\tests\test_remote_runner_bootstrap_deploy.py`
- Modify: `E:\code\bio_ui\tests\test_remote_runner_bootstrap_workflow_runtime.py`
- Modify: `E:\code\bio_ui\tests\test_backend_contract_api.py`
- Modify: `E:\code\bio_ui\scripts\remote_smoke.py`
- Modify: `E:\code\bio_ui\scripts\remote_pipeline_smoke.py`

- [ ] Update tests to expect canary/profile/rollback metadata in existing payloads where relevant.
- [ ] Keep smoke output aligned with the new bootstrap phases so operators can distinguish ready-vs-canary-vs-rollback failures.
- [ ] Leave pytest execution to the user; do only syntax-level verification locally from this Windows environment.

### Verification

**Local verification in this environment:**
- `uv run python -m py_compile core\\remote_runner\\manager.py core\\remote_runner\\client.py core\\app_runtime\\service.py core\\app_runtime\\runner_ops.py apps\\remote_runner\\config.py apps\\remote_runner\\main.py apps\\remote_runner\\executor.py scripts\\remote_smoke.py scripts\\remote_pipeline_smoke.py`

**User-run verification after handoff:**
- Focused pytest for touched remote-runner tests from WSL Codex CLI
- `python scripts/remote_smoke.py --bootstrap`
- `python scripts/remote_pipeline_smoke.py`
