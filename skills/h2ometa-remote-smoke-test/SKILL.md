---
name: h2ometa-remote-smoke-test
description: Use when working in this bio_ui repository and the user asks to run real H2OMeta remote smoke tests, validate the Windows Local API, verify SSH or runner readiness, or do testing work that risks repeating known pytest, WSL/Windows, or config-pollution failures.
---

# H2OMeta Remote Smoke Test

This is the repo-local official entrypoint for real H2OMeta remote testing and for recurring testing mistakes that have already happened in this repository.

Use this skill to do two things:

1. Run the canonical real-test workflows for SSH, Local API, runner bootstrap, pipeline smoke, and database acceptance.
2. Apply repository experience so repeated failures get caught early instead of being rediscovered by trial and error.

## Hard Rules

- Do not run `pytest` from this Windows Codex environment. If real `pytest` is needed, ask the user to run it manually from the WSL Codex CLI.
- Do not use WSL `curl http://127.0.0.1:8765/...` to decide whether the Windows Local API is healthy. That only checks the WSL network namespace.
- Do not treat `C:\Users\Administrator\miniconda3\Scripts\conda.exe run ...` invoked from WSL as a valid fallback for real smoke tests. Open a real Windows PowerShell or cmd session instead.
- Do not let tests write to the real Windows config at `C:/Users/Administrator/AppData/Roaming/H2OMeta/config.json`. Patch `get_config`, `save_config`, keyring, and runner token storage, or redirect app data to a temp directory.
- Do not print passwords, keyring values, bearer tokens, or runner token refs beyond non-sensitive identifiers already stored in config.
- Do not foreground-run `launch_remote_runner.sh` during routine diagnostics. That can start a second runner and overwrite `runner-state.json`.
- Do not treat `service_port: 8876` as a healthy post-bootstrap state. That fixed port is stale after the dynamic-port migration.
- For repeat bootstrap validation, make sure the implementation clears the previous remote service and `shared/runtime/runner-state.json` before starting again.

## Decision Flow

Use this decision path before taking action:

1. If the task is a real remote smoke, start with non-mutating checks: config read, SSH connect, Windows Local API health, `/api/v1/ssh/status`, and `/api/v1/servers`.
2. If the task is a real bootstrap or pipeline smoke, run the canonical skill scripts from `scripts/` and stay on the Windows-side Local API path.
3. If the task is code-testing or verification work, read [test-safety.md](test-safety.md) first and decide whether the work needs syntax-only verification, isolated unit tests, or user-run WSL `pytest`.
4. If the task looks familiar because it matches a prior failure mode, read [pitfalls.md](pitfalls.md) before improvising.

## Canonical Entrypoints

These scripts under this skill are the official entrypoints:

- `python skills/h2ometa-remote-smoke-test/scripts/remote_smoke.py`
- `python skills/h2ometa-remote-smoke-test/scripts/remote_smoke.py --bootstrap`
- `python skills/h2ometa-remote-smoke-test/scripts/remote_pipeline_smoke.py`
- `python skills/h2ometa-remote-smoke-test/scripts/remote_pipeline_database_binding_smoke.py`
- `python skills/h2ometa-remote-smoke-test/scripts/remote_real_database_acceptance.py --rerun-check`

If WSL Python is missing project dependencies such as `keyring`, stop using the WSL shell for this smoke and rerun from a real Windows shell:

```bat
cd /d E:\code\bio_ui
C:\Users\Administrator\miniconda3\Scripts\conda.exe run -n bio_ui python skills/h2ometa-remote-smoke-test/scripts/remote_smoke.py
```

When a real smoke requires the Local API, start it from Windows first:

```bat
cd /d E:\code\bio_ui
run.bat --web
```

Then verify from Windows, not WSL:

```powershell
curl http://127.0.0.1:8765/health
Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8765 -State Listen
```

## Workflow Map

- SSH, Local API, runner readiness: use `scripts/remote_smoke.py`
- Mutating bootstrap validation: use `scripts/remote_smoke.py --bootstrap`
- Minimal end-to-end pipeline path: use `scripts/remote_pipeline_smoke.py`
- Normal Snakemake pipeline database binding: use `scripts/remote_pipeline_database_binding_smoke.py`
- Real production database acceptance: use `scripts/remote_real_database_acceptance.py`
- Additional generated-tool, linear-workflow, or database smoke helpers: use the matching script in `scripts/` only after the control-plane smoke is green

## Experience Library

Read these files when the task needs more than the quick rules above:

- [pitfalls.md](pitfalls.md): recurring failures, symptoms, and recovery paths
- [test-safety.md](test-safety.md): how to avoid pytest, config, keyring, and Local API test mistakes

If a new testing failure repeats, add it to one of those files instead of leaving it only in chat history.
