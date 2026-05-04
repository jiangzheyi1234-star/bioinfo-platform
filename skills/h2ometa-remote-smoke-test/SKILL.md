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

## Windows Local API Startup

When a real smoke requires the local API, start the product entrypoint from Windows first:

```bat
cd /d E:\code\bio_ui
run.bat --web
```

Then verify from Windows, not WSL:

```bat
curl http://127.0.0.1:8765/health
```

or:

```powershell
Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8765 -State Listen
```

If `curl` reports connection refused or PowerShell shows no listener, the failure is at the Windows Local API layer. Do not diagnose SSH, remote runner, or database tools until `apps.api.run` is listening on `127.0.0.1:8765`.

If `run.bat` fails with `The system cannot find the batch label specified - <label>`, inspect the batch file line endings. Mixed LF/CRLF can make `cmd.exe` unable to find labels added near the end of the file. Normalize the `.bat` file to CRLF, then rerun the launcher.

## Database UI Smoke

When validating database template behavior reported from the product UI, do not only register the database through raw API calls. Reproduce through the web database page when possible:

1. Open `http://127.0.0.1:3765/workflows/databases` from a Windows-side browser automation runtime.
2. Click `添加数据库`, choose the template, fill the remote path, click `浏览远程路径`, then use `选择当前目录` / `选择当前路径` before `加入`.
3. Read `/api/v1/databases` after the UI action and verify `status`, `message`, `metadata.validation.toolProbe`, and `metadata.resolvedPath`.

For prefix-style databases, the UI-selected path and the tool path may intentionally differ. Preserve the selected UI path in `path`, but verify `metadata.resolvedPath.prefix` is the value used by the tool probe and generated workflow injection. BLAST alias databases are a common case: selecting a directory containing `core_nt.nal` and split volumes such as `core_nt.00.nhr/.nin/.nsq` should resolve to the prefix `core_nt`, not the directory itself or the single volume prefix `core_nt.00`.

## Real Database Acceptance Smoke

After registering real production databases, use the strict acceptance script to prove template coverage, saved validation metadata, tool probe success, and generated Snakemake database injection:

```bat
C:\Users\Administrator\miniconda3\Scripts\conda.exe run -n bio_ui python skills\h2ometa-remote-smoke-test\scripts\remote_real_database_acceptance.py --rerun-check
```

By default this requires every production template except `custom`: `kraken2`, `bracken`, `blast`, `diamond`, `bowtie2`, `bwa`, `minimap2`, `hisat2`, `star`, `salmon`, `kallisto`, `ncbi_taxonomy`, `metaphlan`, `centrifuge`, `kaiju`, `gtdbtk`, `interproscan`, `silva_qiime`, `sourmash`, `mmseqs2`, `hmmer_pfam`, `checkm`, `humann`, `card_rgi`, and `eggnog_mapper`.

For partial acceptance while real databases are still being staged, pass one or more template filters:

```bat
C:\Users\Administrator\miniconda3\Scripts\conda.exe run -n bio_ui python skills\h2ometa-remote-smoke-test\scripts\remote_real_database_acceptance.py --template kraken2,blast,humann --rerun-check
```

Use `--skip-snakemake` only when you need to isolate registration/probe metadata from generated workflow execution. A production acceptance claim needs the default Snakemake step to complete.

## Recommended Workflow

1. Run the bundled script from the repo root:

```bash
python3 skills/h2ometa-remote-smoke-test/scripts/remote_smoke.py
```

2. If WSL Python lacks project dependencies such as `keyring`, rerun through Windows conda automatically or manually:

```bat
C:\Users\Administrator\miniconda3\Scripts\conda.exe run -n bio_ui python skills\h2ometa-remote-smoke-test\scripts\remote_smoke.py
```

3. If local API is down, start `run.bat --web` from Windows, verify `127.0.0.1:8765/health`, then rerun the smoke. If `8765` has no listener, report a Local API startup problem instead of assuming remote SSH or runner failure.

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
