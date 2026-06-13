# H2OMeta Test Safety

Use this file before doing testing or verification work that could touch the real Windows runtime, Local API, config, keyring, or remote runner state.

## Contents

- Decide what kind of verification is safe
- When to run Windows `pytest` and when to ask for WSL/Linux proof
- Required isolation for risky tests
- Safe validation order

## Decide What Kind Of Verification Is Safe

Use this order:

1. If the task only needs documentation or skill edits, no code execution is required.
2. If the task changes Python files and only needs a quick sanity check, use syntax-level verification from Windows.
3. If the task requires real `pytest`, run it from Windows with the Windows-owned environment and isolated app-data roots unless the task explicitly needs WSL/Linux proof.
4. If the task requires a real remote smoke, use the canonical scripts in `skills/h2ometa-remote-smoke-test/scripts/`.

## Windows Pytest

Windows pytest is allowed after setting the Windows-owned Python environment and isolating runtime persistence:

```powershell
$env:UV_CACHE_DIR='E:\code\bio_ui\.uv-cache-local'
Remove-Item Env:\UV_PYTHON -ErrorAction SilentlyContinue
$env:UV_PROJECT_ENVIRONMENT='E:\code\bio_ui\.venv-win'
$env:UV_PYTHON_INSTALL_DIR='E:\code\bio_ui\.codex-uv-python'
$env:APPDATA='E:\code\bio_ui\.tmp\pytest-appdata\Roaming'
$env:LOCALAPPDATA='E:\code\bio_ui\.tmp\pytest-appdata\Local'
python -m pytest
```

Ask the user for WSL/Linux proof only when:

- The behavior is Linux-specific or WSL-specific
- A release/platform gate explicitly requires Linux semantics
- Windows pytest passes but there is a credible cross-platform parity risk

After pytest, remove `.pytest_cache`, repo-local `__pycache__`, and test-only app-data directories before final reporting.

## Required Isolation For Risky Tests

Any test touching runtime startup, SSH auto-connect, server persistence, or token storage must isolate all real persistence:

- Patch `get_config`
- Patch `save_config`
- Patch keyring access
- Patch runner token storage
- Redirect app data to a temp directory when needed

Unsafe pattern:
- A test with `auto_connect_on_startup=True` that can persist into the real Windows profile

Safe pattern:
- A test that mocks persistence end-to-end or redirects the entire app data root to temp storage

## Safe Validation Order

When you are unsure, use this sequence:

1. Read the task and classify it: docs, code-only verification, or real smoke
2. Check [pitfalls.md](pitfalls.md) for a matching historical failure
3. Choose the lowest-risk validation that still answers the question
4. Run isolated Windows `pytest` when syntax checks and reasoning are not enough
5. Use real smoke scripts only when the user wants real environment validation

## Canonical Real-Test Entrypoints

For real environment validation, do not invent new ad-hoc commands first. Start from:

- `python skills/h2ometa-remote-smoke-test/scripts/remote_smoke.py`
- `python skills/h2ometa-remote-smoke-test/scripts/remote_smoke.py --bootstrap`
- `python skills/h2ometa-remote-smoke-test/scripts/remote_pipeline_smoke.py`
- `python skills/h2ometa-remote-smoke-test/scripts/remote_worker_crash_recovery_acceptance.py`
- `python skills/h2ometa-remote-smoke-test/scripts/remote_real_database_acceptance.py --rerun-check`
