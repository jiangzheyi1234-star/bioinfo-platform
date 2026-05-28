# Remove Legacy Workflow Fallbacks Goal Progress

## 2026-05-13

### Goal Input

Remove H2OMeta workflow legacy template structure and silent fallback paths. Keep fail-loud validation only.

### Verification Log

- Completed: confirmed bundled pipeline entry points only exist at `workflow/Snakefile`.
- Completed: confirmed shared manifest validator rejects root-level `Snakefile`, non-`workflow/Snakefile`, missing `execution.outputs`, and invalid artifact bindings.
- Completed: confirmed runner artifact collection is manifest-driven and does not scan `result_dir`.
- Completed: removed generated workflow default output fallbacks, including implicit `tool-output.txt` and generated `tool --help` command fallback.
- Completed: changed empty generated output paths to fail with `TOOL_OUTPUT_PATH_REQUIRED` instead of defaulting to `tool-output.txt`.
- Completed: rewrote `GOAL_PLAN.md` for this no-legacy cleanup goal.
- Verified: Python `py_compile` passes for runner/catalog files.
- Verified: no root `Snakefile`, default `snakefile`, default generated output, result-dir scan, or default artifact kind/mime mapping remains in the workflow execution path.
- Verified: manifest validator passes for all bundled pipelines.
- Verified: `apps/web` `npm run build` exits 0.
- Verified: restarted API and web dev servers with current code.
- Verified: `/api/v1/workflow-catalog?refresh=true` returns seven runnable pipelines and empty `pipelineError`.
- Verified: browser opened `/workflows`, `/workflows/detail?workflow=file-summary-standard-v1`, and `/workflows/detail?workflow=moving-pictures-16s-rulegraph-v1`.
- Verified: browser routes showed no framework error overlay and no relevant console errors.
- Screenshot evidence saved under `.tmp/no-legacy-goal/`.

### Final Status

All completion conditions passed. No `pytest` command was run from the Windows Codex environment.

## 2026-05-27

### Continuation

- Completed: required managed workflow runtime artifact by default, with remote workflow runtime registration limited to explicit `H2OMETA_ALLOW_REMOTE_WORKFLOW_RUNTIME_REGISTRATION=1` repair use.
- Completed: aligned local and remote workflow runtime manifest validation on declared Snakemake package version.
- Completed: tightened workflow runtime reuse/config verification to include `snakemake_version`.
- Completed: fixed empty Snakemake version handling in workflow runtime bundle packaging.
- Completed: made workflow submission return 503 for readiness failures while keeping input errors as 400.
- Completed: updated workflow readiness UI to require `server.ready`, show nested bootstrap canary evidence, and avoid inferring workflow profile readiness without an explicit profile signal.
- Completed: made remote cleanup preserve managed runtime by default and refuse recursive removal of a non-symlink `current` path.
- Completed: updated the managed workflow runtime runbook to use repo-local `uv run` commands and expanded the WSL-only focused `pytest` handoff list.

### Verification Log

- Verified: Python `py_compile` passes for touched Python source and focused test files.
- Verified: workflow runtime remote build script `--print-remote-script` exits 0.
- Verified: `apps/web` `npm run build` exits 0.
- Verified: `git diff --check` exits 0 with only existing CRLF/LF conversion warnings.
- Verified: `/api/v1/workflow-catalog?refresh=true` returns HTTP 200, seven runnable catalog items, and empty `pipelineError`.
- Verified: browser opened `/workflows`, `/workflows/detail?workflow=file-summary-standard-v1`, and `/workflows/detail?workflow=moving-pictures-16s-rulegraph-v1` with no framework error overlay and no console errors.
- Expected blocker: release artifact preflight fails until `h2ometa-workflow-runtime-0.1.0-linux-64.tar.gz` and its `.sha256` are present locally.
- Not run here: `pytest`; run the focused command from the WSL Codex CLI as documented in `docs/managed-workflow-runtime-runbook.md`.
