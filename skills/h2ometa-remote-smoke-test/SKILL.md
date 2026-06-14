---
name: h2ometa-remote-smoke-test
description: Use when working in this bio_ui repository and the user asks to run real H2OMeta remote smoke tests, validate the Local API, verify SSH or runner readiness, or do testing work that risks repeating known pytest or config-pollution failures.
---

# H2OMeta Remote Smoke Test

This is the repo-local official entrypoint for real H2OMeta remote testing and for recurring testing mistakes that have already happened in this repository.

Use this skill to do two things:

1. Run the canonical real-test workflows for SSH, Local API, runner bootstrap, pipeline smoke, and database acceptance.
2. Apply repository experience so repeated failures get caught early instead of being rediscovered by trial and error.

## Hard Rules

- Windows Codex may run `pytest` when using the Windows-owned Python/uv environment and isolated app-data roots. Do not invoke WSL just to run pytest unless the task explicitly needs WSL/Linux proof.
- Do not let tests write to the real Windows config at `C:/Users/Administrator/AppData/Roaming/H2OMeta/config.json`. Patch `get_config`, `save_config`, keyring, and runner token storage, or redirect app data to a temp directory.
- Do not print passwords, keyring values, bearer tokens, or runner token refs beyond non-sensitive identifiers already stored in config.
- Do not foreground-run `launch_remote_runner.sh` during routine diagnostics. That can start a second runner and overwrite `runner-state.json`.
- Do not treat `service_port: 8876` as a healthy post-bootstrap state. That fixed port is stale after the dynamic-port migration.
- For repeat bootstrap validation, make sure the implementation clears the previous remote service and `shared/runtime/runner-state.json` before starting again.

## Decision Flow

Use this decision path before taking action:

1. If the task is a real remote smoke, start with non-mutating checks: config read, SSH connect, Local API health, `/api/v1/ssh/status`, and `/api/v1/servers`.
2. If the task is a real bootstrap or pipeline smoke, run the canonical repo-local skill entrypoints under `skills/h2ometa-remote-smoke-test/scripts/`.
3. If the task is code-testing or verification work, read [test-safety.md](test-safety.md) first and decide whether the work needs syntax-only verification, isolated Windows pytest, or explicit WSL/Linux proof.
4. If the task looks familiar because it matches a prior failure mode, read [pitfalls.md](pitfalls.md) before improvising.

## Canonical Entrypoints

These scripts under this skill are the official entrypoints:

- `python skills/h2ometa-remote-smoke-test/scripts/remote_smoke.py`
- `python skills/h2ometa-remote-smoke-test/scripts/remote_smoke.py --bootstrap`
- `python skills/h2ometa-remote-smoke-test/scripts/remote_pipeline_smoke.py`
- `python skills/h2ometa-remote-smoke-test/scripts/remote_worker_crash_recovery_acceptance.py`
- `uv run python scripts\remote_two_slot_acceptance.py --allow-two-slot`
- `uv run python scripts\remote_execution_policy_acceptance.py --allow-policy-restart`
- `uv run python scripts\remote_runner_release_gate.py --allow-two-slot --allow-runner-kill --evidence-json dist\remote-runner\release-gate-evidence.json`
- `python skills/h2ometa-remote-smoke-test/scripts/remote_pipeline_database_binding_smoke.py`
- `python skills/h2ometa-remote-smoke-test/scripts/remote_real_database_acceptance.py --rerun-check`

When a real smoke requires the Local API, start it first:

```bat
cd /d E:\code\bio_ui
run.bat --web
```

When validating a local staging remote-runner tarball whose SHA has not been promoted into
`config/remote-runner-release-manifest.json`, start the Local API with the explicit staging gate:

```bat
cd /d E:\code\bio_ui
set H2OMETA_ARTIFACT_CACHE_DIR=E:\code\bio_ui\.tmp\artifact-cache
set H2OMETA_ALLOW_STAGING_REMOTE_RUNNER_BUNDLE=1
set H2OMETA_REMOTE_RUNNER_BUNDLE=E:\code\bio_ui\resources\remote-runner\h2ometa-remote-runner-0.1.1-control-plane-linux-64.tar.gz
run.bat --web
```

Also set the same `H2OMETA_REMOTE_RUNNER_BUNDLE` in the shell that runs
`scripts\remote_runner_release_gate.py`; the gate refuses to run without it.

Then verify the API:

```powershell
curl http://127.0.0.1:8765/health
Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8765 -State Listen
```

## Workflow Map

- SSH, Local API, runner readiness: use `skills/h2ometa-remote-smoke-test/scripts/remote_smoke.py`
- Mutating bootstrap validation: use `skills/h2ometa-remote-smoke-test/scripts/remote_smoke.py --bootstrap`
- Real tool validation starts from the tool search/add flow, then use the generated-tool smoke helpers once the searched tool has a saved contract.
- Minimal end-to-end pipeline path: use `skills/h2ometa-remote-smoke-test/scripts/remote_pipeline_smoke.py`
- Destructive P0-1 worker crash/restart acceptance: use `skills/h2ometa-remote-smoke-test/scripts/remote_worker_crash_recovery_acceptance.py --allow-runner-kill` only on an idle `systemd_user` runner after verifying the deployed release contains the current P0-1 code.
- Real P0-3B 2-slot Snakemake acceptance: use `scripts/remote_two_slot_acceptance.py --allow-two-slot`; it directly probes the remote runner over SSH, temporarily enables the multi-slot gate, and must restore the production default single slot before exiting.
- Real execution policy acceptance: use `scripts/remote_execution_policy_acceptance.py --allow-policy-restart`; it directly probes the remote runner over SSH, temporarily restarts the worker, sends one controlled SIGKILL, proves retry backoff, heartbeat timeout, start-to-close timeout, and queue TTL resource-wait evidence, and must restore the production default single slot before exiting.
- Runtime release gate after staging a runner that changes execution control-plane behavior: use `scripts/remote_runner_release_gate.py --allow-two-slot --allow-runner-kill --evidence-json dist\remote-runner\release-gate-evidence.json`; it runs the real 2-slot Snakemake gate, worker crash/restart gate, and execution policy gate in sequence, then writes machine-readable evidence.
- Normal Snakemake pipeline database binding: use `skills/h2ometa-remote-smoke-test/scripts/remote_pipeline_database_binding_smoke.py`
- Real production database acceptance: use `skills/h2ometa-remote-smoke-test/scripts/remote_real_database_acceptance.py`
- Additional generated-tool, linear-workflow, or database smoke helpers: use the matching script in `skills/h2ometa-remote-smoke-test/scripts/` only after the control-plane smoke is green

## Experience Library

Read these files when the task needs more than the quick rules above:

- [pitfalls.md](pitfalls.md): recurring failures, symptoms, and recovery paths
- [test-safety.md](test-safety.md): how to avoid pytest, config, keyring, and Local API test mistakes

If a new testing failure repeats, add it to one of those files instead of leaving it only in chat history.
