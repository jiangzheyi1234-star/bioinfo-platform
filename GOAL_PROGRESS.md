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
