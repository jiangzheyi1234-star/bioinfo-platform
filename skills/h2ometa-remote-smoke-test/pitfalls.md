# H2OMeta Pitfalls

Use this file when a task matches a failure mode that has already happened in `bio_ui`.

## Contents

- Windows Codex `pytest` isolation failures
- Real config and keyring pollution
- Stale fixed port `8876`
- Duplicate runner startup
- Dirty bootstrap retries
- Browser screenshot capture timeouts
- Historical artifact-edge duplicates during runner upgrade
- Staging deploy direct health payload mismatch
- Two-slot acceptance leaving production defaults changed

## Windows Codex `pytest` Isolation Failures

Symptom:
- `pytest` from Windows fails because it touches real app config, uses a non-Windows executable shim, hits Windows path limits, or relies on POSIX-only test assumptions.

What to do:
- Run Windows pytest only with the Windows-owned environment and isolated `APPDATA`/`LOCALAPPDATA`.
- Fix test fixtures to be cross-platform when the behavior is not Linux-specific.
- Keep POSIX-only behavior explicitly mocked or skipped on Windows.
- Clean `.pytest_cache`, repo-local `__pycache__`, and pytest app-data temp directories before final reporting.

Why this exists:
- Full Windows pytest has been proven to pass, but only after isolating app persistence and removing old POSIX-only assumptions.

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

## Browser Screenshot Capture Timeouts

Symptom:
- Browser verification succeeds through DOM snapshots and clicks, but screenshot capture fails with `Page.captureScreenshot` timeout.
- Retrying through another in-app browser screenshot helper still fails because it uses the same Chrome DevTools Protocol command.
- Windows `CopyFromScreen` may produce a black image or `句柄无效` in the Codex desktop session.

What to do:
- Do not treat screenshot failure as proof that the page failed to render; first validate the UI with DOM snapshots, visible DOM, and real clicks.
- For visual evidence, prefer local Chrome headless screenshot as the fallback:
  `chrome.exe --headless=new --disable-gpu --hide-scrollbars --run-all-compositor-stages-before-draw --virtual-time-budget=15000 --window-size=1400,1000 --screenshot=<output.png> <url>`
- If the first headless screenshot catches a loading state, increase `--virtual-time-budget` or use a page-specific ready marker in a scripted browser runner.
- Record both the DOM assertion result and the screenshot file path in the final verification note.

Why this exists:
- `Page.captureScreenshot` timeouts are a known CDP/Chromium failure mode in Playwright/Puppeteer-style automation, and increasing a timeout alone may not fix it.

## Historical Artifact-Edge Duplicates During Runner Upgrade

Symptom:
- A newly staged runner exits during `SCHEMA_SQL` with
  `UNIQUE constraint failed: run_artifact_edges.run_id, run_artifact_edges.role, run_artifact_edges.port_name`.
- Fresh-database tests pass, but the real runner database contains repeated historical output edges.

What to do:
- Do not delete the runner database or historical lineage rows.
- Keep the adopted-output unique index out of raw `SCHEMA_SQL`.
- Run the idempotent storage migration first: retain the earliest canonical output edge, give later duplicates stable `#legacy-<edge_id>` port names, then create the partial unique index.
- Validate the migration against a pre-existing database fixture before staging the release again.

Why this exists:
- Schema creation and upgrade are different operations. A new uniqueness invariant must reconcile existing data before SQLite can enforce it.

## Staging Deploy Direct Health Payload Mismatch

Symptom:
- `scripts/deploy_remote_runner_staging_artifact.py` rolls back after repeated `/health/ready` probes even though journal logs show HTTP 200 responses.
- The Local API health wrapper reports `ready.ok`, but the remote runner's direct `/health/ready` endpoint returns a health payload with `status`, `checks`, `workflowRuntime`, and `pipelineRegistry`.

What to do:
- For direct remote runner readiness probes, check the direct health payload, for example `status == "ok"`.
- Do not use the Local API wrapped `ready.ok` shape unless the request is going through the Local API server health endpoint.

Why this exists:
- Staging deploy probes the runner over localhost on the remote host, not through the Local API proxy response shape.

## Two-Slot Acceptance Leaving Production Defaults Changed

Symptom:
- After running P0-3B acceptance, the remote runner still reports `concurrency_limit=2`, `slot-1` is active, or the systemd user environment still has `H2OMETA_REMOTE_ENABLE_MULTI_SLOT=1`.
- Later single-slot release or smoke validation behaves differently from production defaults.

What to do:
- Use `scripts/remote_two_slot_acceptance.py --allow-two-slot` or `scripts/remote_runner_release_gate.py --allow-two-slot --allow-runner-kill`; both are expected to restore `run_worker_slot_count=1`, unset the multi-slot environment gate, restart the service, and emit `POST_ACCEPTANCE_INVARIANTS`.
- If a hand-run command fails before cleanup, update `~/.h2ometa/runner/shared/config/runner.json` to single-slot values, unset `H2OMETA_REMOTE_ENABLE_MULTI_SLOT`, `H2OMETA_REMOTE_RUN_WORKER_SLOTS`, `H2OMETA_REMOTE_RUN_WORKER_TOTAL_CPU`, and `H2OMETA_REMOTE_RUN_WORKER_ATTEMPT_CPU` with `systemctl --user unset-environment`, then restart `h2ometa-remote.service`.
- Confirm the current worker has `concurrency_limit=1`, exactly one active `slot-0`, and no allocated resource rows for the acceptance run ids.

Why this exists:
- P0-3B deliberately opens a normally-disabled multi-slot gate for real Snakemake concurrency proof. Release evidence is incomplete unless the gate also proves cleanup back to production defaults.
