# H2OMeta Refactor Plan (2026-04-14)

## Goals
1. Frontend: replace the legacy workflow DAG renderer with a React Flow editor, while keeping `/workspace` as the unified shell entrypoint.
2. Backend: add coverage for Slurm workflow backend behavior, compiler graph validation, and the current preflight output protocol.
3. Infra: move desktop backend boot to an explicit sidecar-oriented model and stop persisting SSH passwords in plaintext config.

## Constraints
- Do not break public workflow domain signatures in `core/workflow/domain.py`.
- Follow the repo rule: no silent fallback, and no stale references to removed fields.
- `pytest` remains user-run in this environment; do not weaken tests or product behavior to accommodate local test gaps.
- Frontend DAG uses `@xyflow/react`.
- Large files should be split rather than extended.

## Verification
- Web build: `npm --prefix apps/web run build`
- Desktop build: `cargo build --manifest-path apps/desktop/src-tauri/Cargo.toml`
- Python tests are prepared and updated, but final `pytest` execution is left to the user per repo policy.
