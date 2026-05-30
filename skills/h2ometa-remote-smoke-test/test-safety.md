# H2OMeta Test Safety

Use this file before doing testing or verification work that could touch the real Windows runtime, Local API, config, keyring, or remote runner state.

## Contents

- Decide what kind of verification is safe
- When to ask the user to run `pytest`
- Required isolation for risky tests
- Safe validation order

## Decide What Kind Of Verification Is Safe

Use this order:

1. If the task only needs documentation or skill edits, no code execution is required.
2. If the task changes Python files and only needs a quick sanity check, use syntax-level verification from Windows.
3. If the task requires real `pytest`, stop and ask the user to run it manually from the project’s normal test environment.
4. If the task requires a real remote smoke, use the canonical scripts in `skills/h2ometa-remote-smoke-test/scripts/`.

## When To Ask The User To Run `pytest`

Ask the user to run `pytest` manually when:

- A regression fix depends on test assertions, not just imports or syntax
- The task changes backend runtime behavior and the only trustworthy check is the existing test suite
- A previously failing `pytest` test needs to be re-run to confirm the bug is gone

Do not try to work around this by running Windows `pytest` anyway.

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
4. Escalate to user-run `pytest` only when syntax checks and isolated reasoning are not enough
5. Use real smoke scripts only when the user wants real environment validation

## Canonical Real-Test Entrypoints

For real environment validation, do not invent new ad-hoc commands first. Start from:

- `python skills/h2ometa-remote-smoke-test/scripts/remote_smoke.py`
- `python skills/h2ometa-remote-smoke-test/scripts/remote_smoke.py --bootstrap`
- `python skills/h2ometa-remote-smoke-test/scripts/remote_pipeline_smoke.py`
- `python skills/h2ometa-remote-smoke-test/scripts/remote_real_database_acceptance.py --rerun-check`
