# H2OMeta Pitfalls

Use this file when a task matches a failure mode that has already happened in `bio_ui`.

## Contents

- Windows Codex `pytest` failures
- Real config and keyring pollution
- Stale fixed port `8876`
- Duplicate runner startup
- Dirty bootstrap retries
- Browser screenshot capture timeouts
- FastQC prepare reaches Snakemake but stalls or misses per-rule tools

## Windows Codex `pytest` Failures

Symptom:
- `pytest` is requested from this Windows Codex environment and fails, hangs, or writes to the wrong runtime context.

What to do:
- Do not run `pytest` here.
- Ask the user to run the needed `pytest` command manually from the project’s normal test environment.
- If you only need quick confidence on touched Python files, prefer syntax-level verification such as `python -m py_compile` or a narrow import check.

Why this exists:
- This repository already documents that Windows Codex is not the place to run `pytest`.

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

## FastQC Prepare Reaches Snakemake But Stalls Or Misses Per-Rule Tools

Symptom:
- `POST /api/v1/tools/prepare` no longer returns 405, but a real FastQC validation still fails below the route layer.
- The UI wrapper path can sit in dry-run while Snakemake clones `https://github.com/snakemake/snakemake-wrappers`.
- A non-wrapper command template can create the per-rule conda env and still fail with `fastqc: command not found`.

What to do:
- First confirm the runner route is present with the release artifact preflight before debugging Snakemake.
- For the UI wrapper path, inspect the dry-run log and running processes before waiting for the full browser request timeout.
- For command-template failures, check whether the per-rule env contains the expected binary and whether Snakemake activation actually puts that env's `bin` directory on `PATH`.
- Remember that the conda-pack `workflow-env/bin/activate` script activates the packed workflow env itself; it is not equivalent to `conda shell.posix activate <per-rule-env>`.

Why this exists:
- A real FastQC prepare on 2026-05-31 reached Snakemake after the prepare route was released. The UI path stalled cloning `snakemake-wrappers`; the command-template path created `fastqc` successfully but Snakemake's shell did not see it because the packed runtime activate script did not activate the per-rule env.
