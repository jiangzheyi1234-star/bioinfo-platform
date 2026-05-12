# Remove Legacy Workflow Fallbacks Goal Plan

## Goal

Completely remove H2OMeta workflow legacy template execution paths and silent fallbacks. Keep only fail-loud validation and explicit diagnostics.

## Scope

- Verify there is no root-level `Snakefile` support or default `snakefile` value.
- Verify there is no default `execution.outputs` mapping.
- Remove generated workflow output defaults such as implicit `tool-output.txt`.
- Verify artifact collection is manifest-driven only.
- Ensure invalid bundled manifests surface through `pipelineError`.
- Update docs/progress language so fallback is only mentioned as prohibited behavior.

## Non-Goals

- Do not add a new workflow engine.
- Do not restore legacy compatibility.
- Do not run `pytest` from Windows Codex.
- Do not rewrite the runner architecture.

## Checkpoints

1. Scan code and docs for legacy/fallback paths.
2. Remove remaining silent generated-output fallbacks.
3. Run manifest validator and root Snakefile check.
4. Run Python compile and `apps/web` build.
5. Verify API catalog and browser detail routes.
