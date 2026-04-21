# Remote Bootstrap Best Practices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce remote bootstrap friction by auto-providing more workflow/runtime prerequisites and surfacing precise remote preflight failures instead of opaque bootstrap errors.

**Architecture:** Keep SSH reachability and remote `python3` as hard prerequisites. Refactor bootstrap into explicit preflight/install stages, auto-provision a managed micromamba toolchain under the runner data root when the host lacks `conda`/`mamba`/`micromamba`, and persist/report structured bootstrap metadata so API health responses can explain the exact blocking condition.

**Tech Stack:** Python, FastAPI, Snakemake, shell bootstrap scripts, pytest

---

### Task 1: Add structured remote preflight + managed workflow runtime provisioning

**Files:**
- Modify: `core/remote_runner/manager.py`
- Modify: `core/remote_runner/bundle.py`

- [ ] **Step 1: Add failing tests for managed workflow runtime fallback and precise bootstrap errors**
- [ ] **Step 2: Refactor bootstrap commands into explicit helper stages for python, venv/pip, workflow runtime, and launcher mode detection**
- [ ] **Step 3: Auto-install a managed micromamba binary into the runner-owned tool directory when no compatible conda-family binary exists**
- [ ] **Step 4: Persist structured bootstrap metadata (preflight/tooling info) in the bootstrap result**
- [ ] **Step 5: Re-run targeted bootstrap tests**

### Task 2: Teach the remote runner to use the managed workflow runtime

**Files:**
- Modify: `apps/remote_runner/config.py`
- Modify: `apps/remote_runner/executor.py`
- Modify: `core/remote_runner/manager.py`

- [ ] **Step 1: Add config fields for managed conda command/root prefix metadata**
- [ ] **Step 2: Update Snakemake execution to export the managed conda command/root prefix when present**
- [ ] **Step 3: Add or update tests proving execution uses the managed runtime without requiring host-global conda**
- [ ] **Step 4: Re-run targeted execution tests**

### Task 3: Surface granular readiness/reporting through the API contract

**Files:**
- Modify: `core/app_runtime/service.py`
- Modify: `tests/test_backend_contract_api.py`
- Modify: `tests/test_remote_runner_control_plane.py`

- [ ] **Step 1: Persist and reuse bootstrap metadata relevant to health/readiness messages**
- [ ] **Step 2: Introduce clearer reason codes/messages for missing python, failed venv/pip setup, unsupported workflow runtime setup, and launcher startup failures**
- [ ] **Step 3: Update API contract tests to assert the more specific behavior where applicable**
- [ ] **Step 4: Run targeted backend/runner test suites**
