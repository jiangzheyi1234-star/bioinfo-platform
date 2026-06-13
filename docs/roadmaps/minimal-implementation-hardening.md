# Minimal Implementation Hardening

Status: Current

Last reviewed: 2026-06-10

Baseline: `main...origin/main`, `HEAD=d2b03368cae323f417420d60b0c7ba1ff6044460`, `origin/main=d2b03368cae323f417420d60b0c7ba1ff6044460`.

Existing dirty files at intake included tool profile, production-evidence, local smoke, release-artifact, roadmap/docs, `pyproject.toml`, `run.bat`, and docs/superpowers deletions. Treat those as pre-existing integrator work; do not revert or overwrite them without a separate decision.

## Decision Card

Decision: Continue as an architecture-track hardening audit with narrow repair slices, not a broad cleanup sweep.

Track: architecture-track.

Why now: Placeholder smoke fixtures and overly broad production-evidence matching can leak into tool contract quality and production claims.

Accepted constraints: Windows owns launcher, UI smoke, `npm run build`, and pytest/Python quality gates with the Windows-owned environment; WSL/Linux proof is reserved for explicit parity needs. Small `tests/` and `.test/fixtures` samples are preserved unless they affect product contracts or production evidence.

Rejected alternatives: Do not remove every fallback or demo mention globally. Do not add silent compatibility branches. Do not replace real-data acceptance with tiny smoke fixtures.

Ownership split: Integrator owns this roadmap and final proof; Worker B owns tool-profile smoke fixture hardening; Worker C owns local web smoke; Worker D owns one frontend component-family split per later slice; Worker E owns production-evidence matching and event storage.

Proof required: Windows `npm run build`, local smoke when the launcher is running, and Windows pytest/Python commands for focused tests; WSL/Linux pytest only for explicit parity gaps.

Stop conditions: Existing dirty-file conflict, Windows/WSL environment mismatch, or repeated smoke failure that needs a repo-local pitfall note.

Cleanup: Remove verification-only repo artifacts such as `apps/web/.next`, `apps/web/out`, and `apps/web/test-results` before final reporting if created during proof.

This audit tracks intentionally small implementations, placeholder fixtures, fallback paths, and MVP surfaces. The goal is not to make every small fixture production-sized. The goal is to harden paths that can affect real user workflows, production evidence, tool contracts, or long-term maintainability while preserving fast smoke and test feedback loops.

## Classification Rule

- `keep`: The small implementation is intentionally scoped to tests, smoke, or fast local feedback and should remain small.
- `upgrade`: The implementation can affect product behavior, contract quality, production evidence, or operator confidence and should be hardened.
- `decision-needed`: The implementation crosses launcher, desktop, release, remote data, or UX boundaries and needs an integrator decision before workers edit it.

## Agent Fleet Split

- Integrator owns this file, branch baseline, final proof, and cleanup.
- Scout A is read-only and expands this audit with file/line evidence.
- Worker B owns tool profile smoke fixture hardening in `apps/api/tool_profile_open_source_pack.py` and focused tests.
- Worker C owns local UI smoke coverage in `scripts/local_web_smoke.ps1`, `apps/web/package.json`, and focused frontend smoke tests.
- Worker D owns frontend maintainability slices under `apps/web/app/components`, one component family at a time.
- Worker E owns production evidence hardening in `apps/remote_runner/production_evidence.py`, `apps/remote_runner/tools.py`, and focused evidence tests.

## Findings

| Area | Status | Evidence | Decision |
| --- | --- | --- | --- |
| Test fakes and fixtures | keep | `tests/` uses fake managers, fake shell services, tiny demo payloads, and helper-created files. | Preserve. These keep WSL pytest fast and deterministic. |
| Bundled pipeline `.test/fixtures` | keep | `apps/remote_runner/pipelines/*/.test/fixtures/example.txt` and `.test/run-config.json` are dry-run/smoke fixtures. | Preserve as small fixtures unless a pipeline contract requires richer test data. |
| Remote smoke sample reads | keep | `scripts/remote_pipeline_smoke.py` and database-binding smoke use tiny FASTQ bytes. | Preserve. Real data acceptance belongs in dedicated remote acceptance scripts, not minimal smoke. |
| Tool profile BAM smoke fixtures | upgrade | `apps/api/tool_profile_open_source_pack.py` contains `BAM placeholder` smoke content for BAM-consuming profiles. The catalog target acceptance code flags placeholder smoke content. | Replace placeholder content with deterministic minimal SAM text where the rule can consume text-compatible alignment input, or mark profile completion requirements explicitly if a binary BAM is truly required. |
| Tool revision production evidence | upgrade | `apps/remote_runner/production_evidence.py` accepts generated-tool-run evidence, including workflow nodes that reference published `toolRevisionId`. | Production promotion for a registered tool with a current `toolRevisionId` must match that exact revision, not merely any revision that resolves to the same canonical tool id. |
| WorkflowDesignDraft generated UI smoke | upgrade | `docs/roadmaps/durable-control-plane.md` lists save -> validate -> compile -> submit UI smoke as a next priority. | Add browser/UI smoke in a later Worker C slice after local smoke remains stable. |
| Frontend oversized component files | upgrade | Several source files exceed 20 KB, including `tools-page-ui.tsx`, `workflow-dag-preview.tsx`, and `generated-workflow-builder.tsx`. | Split by component family in Worker D slices; do not mix refactors with behavior changes. |
| Desktop repo backend fallback | decision-needed | `apps/desktop/src-tauri/src/main.rs` allows repo backend fallback in dev/Windows with explicit environment controls. | Keep until desktop packaging requirements are reviewed; do not remove as a generic fallback cleanup. |
| Moving Pictures sample download | decision-needed | `apps/api/workflow_sample_data_service.py` downloads official QIIME 2 sample data over the network. | Decide caching/offline behavior separately; do not replace with tiny local fixtures if the UI promise is official sample data. |
| Minimal/demo bundled pipelines | decision-needed | `file-summary-v1`, `branch-merge-analysis-v1`, and related templates are small runnable demos; `file-summary-standard-v1` demonstrates the fuller standard layout. | Upgrade only if product catalog positioning changes from demo/smoke to production template. |

## First Hardening Slice

Worker B starts with BAM smoke fixtures because they directly affect tool contract quality and catalog target acceptance. The patch must avoid fake production claims: if a tool command requires a true binary BAM, the profile must not pretend a placeholder text file is production-ready.

Current result: BAM-consuming curated profiles now use deterministic SAM text smoke inputs and invoke `samtools view -bS` before BAM-consuming tools. Target-acceptance tests should verify these are materialized smoke fixtures, not placeholder content.

## Second Hardening Slice

Worker E tightens production evidence matching for generated-tool-run evidence. A run node that references an old published revision may still resolve to the same canonical tool id for audit visibility, but production enablement for a registered tool with a current `toolRevisionId` must require evidence from that exact revision.

Current result: Production evidence validation now accepts published revision nodes, rejects evidence for an older revision when a registered tool has a newer current revision, and records the accepted current `toolRevisionId` in the production evidence ledger event.

## Third Hardening Slice

Worker C keeps local UI smoke minimal but broad enough to catch stale Next chunks and generated-tool detail regressions. The local smoke script checks Local API health, core API collections, route HTML for workflow pages, the `generated-tool-run-v1` detail route, and at least one `/_next/static/css/...` asset.

Current result: `apps/web` exposes `npm run smoke:local`; `scripts/local_web_smoke.ps1` parses in Windows PowerShell 5 and PowerShell 7, uses ASCII route/chunk assertions, and covers `/workflows/detail?workflow=generated-tool-run-v1`.

## Proof Boundary

Windows proof completed from this environment:

- `powershell -NoProfile -ExecutionPolicy Bypass -Command "[void][scriptblock]::Create((Get-Content -Raw scripts/local_web_smoke.ps1)); Write-Output 'LOCAL_WEB_SMOKE_PS5_PARSE_OK'"`
- `pwsh -NoProfile -ExecutionPolicy Bypass -Command "[void][scriptblock]::Create((Get-Content -Raw scripts/local_web_smoke.ps1)); Write-Output 'LOCAL_WEB_SMOKE_PS7_PARSE_OK'"`
- `node -e "const fs=require('fs'); const s=fs.readFileSync('scripts/local_web_smoke.ps1','utf8'); for (const x of ['/workflows/detail?workflow=generated-tool-run-v1','app/workflows/detail/page.js','Assert-NextStaticAsset']) if(!s.includes(x)) throw new Error('missing '+x); console.log('LOCAL_WEB_SMOKE_STRUCTURE_OK')"`
- `git diff --check -- ...`
- `npm run build` from `apps/web`

Local smoke was not run because `http://127.0.0.1:8765/health` and `http://127.0.0.1:3765/workflows` did not respond within the short probe timeout. Run it after starting the launcher with `run.bat --web`.

Cleanup completed: `apps/web/.next` and `apps/web/out` were removed after `npm run build`; no `apps/web/test-results` directory was present.

Focused WSL proof command:

```bash
export UV_PROJECT_ENVIRONMENT=/tmp/bio_ui_codex_uv_venv_pytest
export UV_CACHE_DIR=/tmp/bio_ui_codex_uv_cache
unset UV_PYTHON
export UV_PYTHON_INSTALL_DIR=/tmp/bio_ui_codex_uv_python
uv run pytest tests/test_tool_catalog_target_acceptance.py tests/test_tool_contract_production_evidence.py tests/test_evidence_ledger.py tests/test_local_web_smoke_script.py
```
