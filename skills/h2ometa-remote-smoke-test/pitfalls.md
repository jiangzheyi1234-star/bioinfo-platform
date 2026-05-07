# H2OMeta Pitfalls

Use this file when a task matches a failure mode that has already happened in `bio_ui`.

## Contents

- Windows Codex `pytest` failures
- WSL versus Windows Local API confusion
- Real config and keyring pollution
- Stale fixed port `8876`
- Duplicate runner startup
- Dirty bootstrap retries

## Windows Codex `pytest` Failures

Symptom:
- `pytest` is requested from this Windows Codex environment and fails, hangs, or writes to the wrong runtime context.

What to do:
- Do not run `pytest` here.
- Ask the user to run the needed `pytest` command manually from the WSL Codex CLI.
- If you only need quick confidence on touched Python files, prefer syntax-level verification such as `python -m py_compile` or a narrow import check.

Why this exists:
- This repository already documents that Windows Codex is not the place to run `pytest`.

## WSL Versus Windows Local API Confusion

Symptom:
- `curl http://127.0.0.1:8765/health` from WSL says connection refused, but the Windows desktop stack may still be the thing that matters.

What to do:
- Treat WSL `127.0.0.1` as the wrong observer for Windows Local API health.
- Re-run the health check from Windows PowerShell or Windows conda.
- Do not call `C:\Users\Administrator\miniconda3\Scripts\conda.exe` from inside WSL as a substitute for a Windows shell.
- If no Windows listener exists on `127.0.0.1:8765`, diagnose Local API startup before touching SSH or the remote runner.

Why this exists:
- WSL and Windows do not share the same localhost view for this workflow.

## Real Config And Keyring Pollution

Symptom:
- A test or helper writes into `C:/Users/Administrator/AppData/Roaming/H2OMeta/config.json`, keyring, or persisted runner token storage.

What to do:
- Patch `get_config`, `save_config`, keyring, and runner token storage in tests.
- Redirect app data to a temp directory for any test touching startup or auto-connect paths.
- Treat any test with `auto_connect_on_startup=True` as unsafe unless persistence is isolated.

Why this exists:
- A previous bad test polluted the saved Windows config with fake server data.

## Stale Fixed Port `8876`

Symptom:
- A health or bootstrap flow reports `service_port: 8876` after work that should have used dynamic ports.

What to do:
- Treat that as stale state, not as success.
- Re-check the saved server state after bootstrap and confirm a dynamically assigned remote port was persisted.

Why this exists:
- The repository migrated away from the old fixed-port behavior.

## Duplicate Runner Startup

Symptom:
- Diagnostics are performed by foreground-running `launch_remote_runner.sh`, after which state or process information becomes confusing.

What to do:
- Do not start a second foreground runner during diagnostics.
- Use read-only probes such as `scripts/remote_artifact_probe.py` and service/log inspection instead.

Why this exists:
- A second runner can overwrite `runner-state.json` and hide the real failure.

## Dirty Bootstrap Retries

Symptom:
- A repeat bootstrap behaves inconsistently because an old service, old process, or old `runner-state.json` is still present.

What to do:
- Stop `h2ometa-remote.service`.
- Kill stale `remote_runner.run`.
- Remove `shared/runtime/runner-state.json`.
- Then retry bootstrap through the Windows Local API path.

Why this exists:
- Reusing dirty state makes bootstrap results hard to trust.
