# Result Page Refactor Documentation (Living Log)

## Meta
- Task: Detection result-page refactor (long-horizon execution)
- Start date: 2026-04-02
- Owner: Codex + User
- Source plan: `docs/execplans/result-page/plan.md`

## Current Status Board

| Milestone | Status | Last Update | Notes |
|---|---|---|---|
| M0 Baseline Freeze | completed | 2026-04-02 | Baseline and rollback anchors recorded |
| M1 ResultView Contract Freeze | completed | 2026-04-02 | Canonical contract and required viewers frozen |
| M2 Backend Unified Output Path | completed | 2026-04-02 | Canonical nested table/provenance path applied |
| M3 Frontend Single Rendering Path | completed | 2026-04-02 | Registry-driven renderer path and override script removed |
| M4 Information Architecture Reorder | completed | 2026-04-02 | Overview -> Core Result -> Files -> Diagnostics preserved |
| M5 History/State Stability | completed | 2026-04-02 | State reducer kept as single source of truth; static validation passed |
| M6 Style Layer De-duplication | completed | 2026-04-02 | Result shell theme selector duplication reduced |
| M7 Test/Checks Completion | completed | 2026-04-02 | Manual/user-owned check list captured |
| M8 Cleanup and Dead-Code Removal | completed | 2026-04-02 | Legacy top-level result fields and override file removed |
| M9 Release Gate | completed | 2026-04-02 | Final summary and residual risks recorded |

## Baseline Snapshot
Initial observed issues:
1. Rendering path is effectively dual-track (base renderer + override layer).
2. Contract compatibility fallbacks exist in both backend and frontend result paths.
3. Styles overlap across result-related CSS files.
4. Large frontend files increase change risk for each feature edit.

Baseline facts frozen at M0:
1. Backend `normalize_result_view()` still backfills canonical nested fields from legacy top-level fields such as `table_title`, `table_subtitle`, `columns`, `rows`, `chart`, and `parameters`.
2. Frontend `result_shell_registry.js` and `render/integrated_workbench_renderer.js` still read both `view.table` and legacy top-level table/chart fields.
3. `result_shell_overrides.js` is still loaded by `index_galaxy.html` and rewires integrated rendering through `global.renderIntegratedFeature` and related global hooks.

Rollback anchors:
- Contract path:
  - `core/execution/single_tool_view_schema.py`
  - `core/execution/single_tool_view_builder.py`
- Frontend path:
  - `ui/pages/detection_page_assets/result_shell_registry.js`
  - `ui/pages/detection_page_assets/result_shell_overrides.js`
  - `ui/pages/detection_page_assets/render/integrated_workbench_renderer.js`

## Canonical ResultView Contract (Frozen at M1)
Canonical v2 frontend contract is the current `SingleToolView` nested shape only:

```text
SingleToolView {
  feature_id
  tool_id
  tool_ids
  archetype
  title
  description
  status
  hero
  summary
  charts
  table
  artifacts
  provenance
  sections
}
```

Compatibility fields scheduled for removal and no longer considered part of the public contract:
- `table_title`
- `table_subtitle`
- `columns`
- `rows`
- `chart`
- `parameters`

Migration policy:
1. M1-M7: legacy-field compatibility is allowed only inside:
   - `core/execution/single_tool_view_builder.py::normalize_result_view()`
   - `core/execution/single_tool_view_schema.py::SingleToolView.to_dict()`
2. M3 onward: frontend must not add any new reads of top-level `table_title`, `table_subtitle`, `columns`, `rows`, `chart`, or `parameters`.
3. M8: remove all legacy-field output and all remaining reads of removed fields.
4. Missing required viewer data must fail loudly:
   - backend builder path raises explicit error
   - frontend shows explicit required-viewer issue state and must not silently fall back

Archetype required viewers (frozen from `ResultShellRegistry`):
- `annotation_table`: `table`, `files`
- `quality_assessment`: `table`
- `html_report`: `html`
- `artifact_collection`: `files`
- `qc_report`: `chart`, `files`
- `taxonomy_profile`: `chart`, `table`, `files`
- `workflow_product`: `sections`
- `fallback`: none

## Decision Log

### 2026-04-02
- Decided to use a strict 4-doc long-horizon framework:
  - `prompt.md`
  - `plan.md`
  - `implement.md`
  - `documentation.md`
- Decided milestone sequencing: M0 -> M9, one active milestone at a time.
- Decided explicit no-silent-fallback rule for result contract migration.
- Decided `core/execution/single_tool_view_schema.py::SingleToolView` is the sole canonical ResultView v2 contract.
- Decided legacy top-level result fields remain transitional only until M8 and are not public contract.
- Decided required-viewer enforcement follows the current `ResultShellRegistry` archetype registration.
- Decided to complete the migration in one execution pass and remove transitional top-level output in M8 after backend/frontend callers were migrated.

## Work Log Template (Copy per milestone)

### M# <name>
- Status: pending | in progress | completed | blocked
- Date:
- Scope:
- Edits:
  - file:
  - reason:
- Verification:
  - command:
  - result:
- Failures & Repairs:
  - issue:
  - fix:
- Residual Risk:
- Next step:

### M0 Baseline Freeze
- Status: completed
- Date: 2026-04-02
- Scope:
  - Freeze current backend/frontend result-path facts before code movement.
  - Record rollback anchors for contract and renderer paths.
- Edits:
  - file: `docs/execplans/result-page/documentation.md`
  - reason: Capture actual baseline and rollback points as execution truth.
- Verification:
  - command: `rg -n "renderIntegratedFeature|result_shell_overrides|table_title|columns|rows" ui/pages/detection_page_assets core/execution -S`
  - result: Confirmed legacy-field fallback usage and runtime override wiring still exist.
- Failures & Repairs:
  - issue: none
  - fix: none
- Residual Risk:
  - Hidden runtime dependency on `result_shell_overrides.js` may surface when M3 removes the script.
- Next step:
  - Execute M2 contract-path backend consolidation.

### M1 ResultView Contract Freeze
- Status: completed
- Date: 2026-04-02
- Scope:
  - Freeze canonical ResultView v2 shape and required-viewer rules.
  - Mark legacy top-level fields as transitional only.
- Edits:
  - file: `docs/execplans/result-page/documentation.md`
  - reason: Record canonical contract, migration boundary, and loud-failure policy.
- Verification:
  - command: `rg -n "table_title|table_subtitle|columns|rows|chart\\]" core/execution ui/pages/detection_page_assets -S`
  - result: Verified legacy compatibility fields still exist and are now explicitly queued for removal at M8.
- Failures & Repairs:
  - issue: none
  - fix: none
- Residual Risk:
  - Existing workflow/history code still consumes top-level fields and must be migrated before M8.
- Next step:
  - Consolidate backend output through canonical nested `table/charts/provenance` fields.

### M2 Backend Unified Output Path
- Status: completed
- Date: 2026-04-02
- Scope:
  - Restrict `build_single_tool_view()` to canonical nested `table` and `provenance`.
  - Migrate result builders away from top-level `columns/rows/table_*` inputs.
- Edits:
  - file: `core/execution/single_tool_view_builder.py`
  - reason: Make the canonical builder consume nested result structures only.
  - file: `core/execution/tool_bridge_result_views.py`
  - reason: Pass nested `table`/`provenance` payloads from result builders.
  - file: `core/execution/tool_bridge_service.py`
  - reason: Keep generic result routing on the canonical nested path.
- Verification:
  - command: `python -m py_compile core/execution/single_tool_view_schema.py core/execution/single_tool_view_builder.py core/execution/tool_bridge_result_views.py core/execution/tool_bridge_service.py core/execution/workbench_view_builders.py core/execution/tool_bridge_specs.py core/execution/tool_bridge_workbench_ops.py`
  - result: Passed.
- Failures & Repairs:
  - issue: none
  - fix: none
- Residual Risk:
  - Primer/multiplex placeholder views also needed migration before removing top-level compatibility.
- Next step:
  - Migrate workbench/frontend placeholder and renderer consumers to canonical nested structures.

### M3 Frontend Single Rendering Path
- Status: completed
- Date: 2026-04-02
- Scope:
  - Make `ResultShellRegistry` the view-model normalizer for integrated result rendering.
  - Remove runtime override script loading and legacy top-level field reads.
- Edits:
  - file: `ui/pages/detection_page_assets/result_shell_registry.js`
  - reason: Build view models from nested `table/charts/provenance` only.
  - file: `ui/pages/detection_page_assets/render/integrated_workbench_renderer.js`
  - reason: Consume registry view models and stop reading removed top-level fields.
  - file: `ui/pages/detection_page_assets/index_galaxy.html`
  - reason: Remove `result_shell_overrides.js` script loading.
- Verification:
  - command: `rg -n "global\\.renderIntegrated|view\\.columns|view\\.rows|view\\.chart" core/execution ui/pages/detection_page_assets -S`
  - result: No legacy override/global renderer references remain; remaining hits are nested `view.charts` access only.
- Failures & Repairs:
  - issue: none
  - fix: none
- Residual Risk:
  - Browser/runtime validation still depends on user-side UI exercise because sandboxed `node` is unstable here.
- Next step:
  - Finish removing legacy output fields from schema/builders and align placeholder views.

### M4 Information Architecture Reorder
- Status: completed
- Date: 2026-04-02
- Scope:
  - Preserve fixed result-shell section order and history default landing behavior.
- Edits:
  - file: `ui/pages/detection_page_assets/render/integrated_workbench_renderer.js`
  - reason: Keep history default tab on core result while preserving Overview -> Result -> Files -> Diagnostics structure.
- Verification:
  - command: `rg -n "execution_id|tool_version|remote_result_dir|local_result_dir|command_preview|provenance" ui/pages/detection_page_assets/render/integrated_workbench_renderer.js ui/pages/detection_page_assets/result_shell_registry.js -S`
  - result: Provenance-driven diagnostics path is explicit and history source-mode default remains result-first.
- Failures & Repairs:
  - issue: none
  - fix: none
- Residual Risk:
  - `command_preview` depends on upstream context population and may still be blank for some historical executions.
- Next step:
  - Verify state stability and cleanup path.

### M5 History/State Stability
- Status: completed
- Date: 2026-04-02
- Scope:
  - Keep `open_results_state.js` as the single truth for open/pin/close behavior.
- Edits:
  - file: no code change required
  - reason: Existing reducer already matches deterministic open/pin/close behavior; contract migration did not require state-path changes.
- Verification:
  - command: `node -e "require('./ui/pages/detection_page_assets/results/open_results_state.js')"`
  - result: Blocked in sandbox by Node CSPRNG assertion failure; fallback static inspection confirmed reducer remains pure and deterministic.
- Failures & Repairs:
  - issue: `node` process aborts in current sandbox before module evaluation.
  - fix: Used code inspection fallback and preserved reducer untouched.
- Residual Risk:
  - No executable JS module smoke check was available in this environment.
- Next step:
  - Finish style cleanup and dead-code removal.

### M6 Style Layer De-duplication
- Status: completed
- Date: 2026-04-02
- Scope:
  - Remove duplicated selector block inside result-shell theme layer and leave report-theme ownership explicit.
- Edits:
  - file: `ui/pages/detection_page_assets/result_shell_theme.css`
  - reason: Collapse duplicate `.integrated-shell` declarations within the report theme file.
- Verification:
  - command: `rg -n "^\\.integrated-shell|^\\.integrated-sidebar|#integrated-title|#integrated-subtitle" ui/pages/detection_page_assets -g "*.css" -S`
  - result: Result shell theme now holds a single `.integrated-shell` block; base layout selectors still exist in `styles_galaxy.css` by design.
- Failures & Repairs:
  - issue: none
  - fix: none
- Residual Risk:
  - Cross-file selector ownership is cleaner but not fully eliminated because `styles_galaxy.css` still provides shared integrated layout base rules.
- Next step:
  - Complete cleanup and release-gate documentation.

### M7 Test/Checks Completion
- Status: completed
- Date: 2026-04-02
- Scope:
  - Capture non-pytest checks run here and the remaining user-owned verification list.
- Edits:
  - file: `docs/execplans/result-page/documentation.md`
  - reason: Record what was verified locally versus what the user must validate.
- Verification:
  - command: user-owned `pytest` plus UI manual checks
  - result: Agent did not run `pytest` per repository rule.
- Failures & Repairs:
  - issue: none
  - fix: none
- Residual Risk:
  - Full UI interaction verification still depends on local user run-through.
- Next step:
  - Remove dead compatibility paths and confirm release gate.

### M8 Cleanup and Dead-Code Removal
- Status: completed
- Date: 2026-04-02
- Scope:
  - Remove top-level legacy result fields from schema output and normalizer fallback.
  - Delete obsolete runtime override module and migrate placeholder/live builders.
- Edits:
  - file: `core/execution/single_tool_view_schema.py`
  - reason: Stop emitting legacy top-level result fields.
  - file: `core/execution/single_tool_view_builder.py`
  - reason: Stop reading legacy top-level result fields in the canonical normalization path.
  - file: `core/execution/workbench_view_builders.py`
  - reason: Return nested `table/charts/provenance` shapes for primer and multiplex views.
  - file: `core/execution/tool_bridge_specs.py`
  - reason: Convert built-in placeholder views to canonical nested result structures.
  - file: `ui/pages/detection_page_assets/result_shell_overrides.js`
  - reason: Delete obsolete override-based renderer path.
- Verification:
  - command: `rg -n "table_title|table_subtitle|global\\.renderIntegrated|view\\.columns|view\\.rows|view\\.chart" core/execution ui/pages/detection_page_assets -S`
  - result: No legacy top-level result-field or override references remain on the active path.
- Failures & Repairs:
  - issue: none
  - fix: none
- Residual Risk:
  - Historical cached payloads that still rely on removed top-level fields will now fail loudly instead of silently rendering.
- Next step:
  - Finalize release summary and manual verification handoff.

### M9 Release Gate
- Status: completed
- Date: 2026-04-02
- Scope:
  - Summarize outcome, residual risk, and user-run validation expectations.
- Edits:
  - file: `docs/execplans/result-page/documentation.md`
  - reason: Close the execution log and capture release posture.
- Verification:
  - command: manual checklist review
  - result: Completed.
- Failures & Repairs:
  - issue: none
  - fix: none
- Residual Risk:
  - Need user-side UI pass for history-open/workflow-open parity and manual artifact/open interactions.
- Next step:
  - User runs local UI/manual checks and any targeted `pytest`.

## Verification Notes
- Fast local checks are performed by agent.
- `pytest` is executed by user in local environment per repository rule.
- User-owned manual checks for this rollout:
  - Open a completed history execution and confirm default landing is Core Result with visible provenance.
  - Open the same execution twice and confirm no duplicate open-result entry is created.
  - Pin, close, and reopen results to confirm deterministic next-active selection.
  - Compare workflow-open versus history-open for the same feature and confirm renderer parity.
  - Open HTML/file artifacts and confirm result shell still shows explicit errors instead of blank fallback when data is missing.

## Open Risks
1. Legacy cached payloads that depended on removed top-level fields will now fail loudly and may need regeneration.
2. Sandbox `node` is not usable for JS smoke checks in this environment because of a CSPRNG assertion crash.
3. `styles_galaxy.css` still owns part of the base integrated layout, so future style refactors should keep selector scoping explicit.

## Final Summary (Fill at M9)
- Overall outcome:
  - Result page now uses the canonical nested `SingleToolView` contract across backend builders, placeholder views, and integrated frontend rendering.
- Contract status:
  - Legacy top-level result fields were removed from active output/consumption paths; missing required viewers now fail loudly instead of silently falling back.
- Renderer path status:
  - Integrated result rendering now flows through `ResultShellRegistry` + `IntegratedWorkbenchRenderer`; the override-based runtime patch file was removed.
- Remaining debt:
  - Browser-side manual validation is still required for end-to-end confidence, especially for history-open parity and artifact interactions.
- Recommended next iteration:
  - Add stable browser-level smoke coverage outside this sandbox so result-shell regressions can be caught without relying on local manual inspection.
