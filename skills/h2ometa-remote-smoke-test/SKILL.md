---
name: h2ometa-remote-smoke-test
description: Validate this repository's H2OMeta remote server setup, SSH connectivity, local API status, remote runner bootstrap health, and dynamic runner port behavior. Use when the user asks to test the real H2OMeta server, verify remote runner health, check whether the configured SSH server can connect, or diagnose bootstrap/runner readiness for this bio_ui project.
---

# H2OMeta Remote Smoke Test

Use this skill only inside the `bio_ui` repository. It is project-specific and must not store server passwords, keyring secrets, or runner tokens in the skill.

## Core Rules

- Read SSH target data from the project configuration via Windows conda environment `bio_ui` when available.
- Do not use WSL `curl http://127.0.0.1:8765/...` to judge whether the Windows Local API is running; that only tests the WSL network namespace and can produce false negatives.
- Do not run unit/integration tests in a way that writes to the real Windows config at `C:/Users/Administrator/AppData/Roaming/H2OMeta/config.json`; tests must patch `get_config`, `save_config`, keyring, and runner token storage or redirect app data to a temp directory.
- Do not print passwords, keyring values, bearer tokens, or runner token refs beyond non-sensitive identifiers already present in config.
- Start with non-mutating checks: config read, SSH connect test, local API health, `/api/v1/ssh/status`, `/api/v1/servers`.
- For real H2OMeta remote runner startup, bootstrap, smoke tests, or Windows Local API validation, use this skill's workflow before running commands; do not start or validate these flows from WSL directly.
- Run bootstrap only when the user explicitly asks for a real remote bootstrap test.
- Treat `service_port: 8876` as stale after the dynamic-port migration; a successful new bootstrap should save a dynamically assigned remote port.
- Do not manually foreground-run `launch_remote_runner.sh` during routine diagnostics; it can create a second runner process and overwrite `runner-state.json`.
- For repeat bootstrap testing, make sure the implementation clears the previous remote service first: stop `h2ometa-remote.service`, kill stale `remote_runner.run`, and remove `shared/runtime/runner-state.json`.
- When validating changed remote runner/backend service logic, do not rely on idempotent reuse. Rebuild the Linux artifact from the changed code, remove the remote installed release/state, then bootstrap once from Windows.

## Known Good Connection Pattern

The current project configuration has been successfully read through Windows conda and SSH-connected using:

```bat
C:\Users\Administrator\miniconda3\Scripts\conda.exe run -n bio_ui python ...
```

The successful SSH check returned:

```text
ok=True, message=Connected, host=192.168.0.152, port=22, user=zyserver
```

This is not a credential. It documents the verified command path and non-secret target metadata.

When testing the real Windows desktop flow, start SSH through the Windows runtime, not WSL Python. The saved key path is a Windows path such as `C:/Users/Administrator/AppData/Roaming/H2OMeta/ssh/...`; WSL Python will not resolve it unless the path is explicitly translated to `/mnt/c/...`.

For product-level validation, use `run.bat` from Windows so the Local FastAPI process reads the same Windows config, key file, and keyring context that the Tauri app uses.

If Local API status must be checked from an agent session, run the check through Windows PowerShell or Windows conda so `127.0.0.1:8765` refers to the Windows host process, not WSL.

Before running tests that touch `RuntimeService.initialize()` or auto-connect, verify they cannot call real `save_config()` or real keyring/token writes. A previous bad test polluted the Windows config with `tester@192.168.0.10`; treat any test using `auto_connect_on_startup=True` as unsafe unless config persistence is mocked or redirected.

## Recommended Workflow

1. Run the bundled script from the repo root:

```bash
python3 skills/h2ometa-remote-smoke-test/scripts/remote_smoke.py
```

2. If WSL Python lacks project dependencies such as `keyring`, rerun through Windows conda automatically or manually:

```bat
C:\Users\Administrator\miniconda3\Scripts\conda.exe run -n bio_ui python skills\h2ometa-remote-smoke-test\scripts\remote_smoke.py
```

3. If local API is down, report that clearly instead of assuming auto-connect state.

4. To run a real bootstrap, require explicit user intent and use:

```bash
python3 skills/h2ometa-remote-smoke-test/scripts/remote_smoke.py --bootstrap
```

5. If the remote runner code, launch scripts, artifact format, or bootstrap semantics changed, first do a clean-install validation:

- Build or refresh `dist/remote-runner/h2ometa-remote-runner-0.1.0-control-plane-linux-64.tar.gz` and `.sha256` from the changed code.
- Stop the remote service and remove only the installed runner release/current pointer/state; preserve shared data/uploads/results unless explicitly asked to purge them.
- Run bootstrap from the Windows API.

6. After bootstrap, verify:

- `/api/v1/servers/{serverId}/health` has `ready.ok == true`.
- The saved `service_port` is a dynamic port and not the old fixed `8876`.
- The remote runner health comes through the SSH tunnel.
- Use `scripts/remote_artifact_probe.py` only for read-only state/process checks after bootstrap; do not add foreground launch commands to it.
- A second bootstrap without rebuilding/changing the artifact should reuse the existing runner; the remote PID and `startedAt` should remain unchanged.

## Failure Diagnosis

- SSH fails: report host, port, user, and message only.
- Local API fails: ask the user to start `run.bat --desktop` or `run.bat --web`.
- Bootstrap fails before health: inspect artifact build/upload, bundled `runtime/bin/python`, launch script, and state file readiness. Do not fall back to remote venv/pip/micromamba installation in bootstrap.
- Health fails after bootstrap: check `reasonCode`, `ready.message`, and whether dynamic `service_port` was saved.
- If a repeat bootstrap leaves stale state, rerun bootstrap after verifying the code path clears the old service/state; do not manually start a second foreground runner.
