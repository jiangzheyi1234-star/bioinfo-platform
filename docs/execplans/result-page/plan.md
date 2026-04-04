# Result Page Refactor Plan

## Execution Rules
1. This file is the only execution source of truth for this task.
2. Only one milestone may be `in progress` at a time.
3. Every milestone must define:
   - outputs
   - acceptance criteria
   - verification method
4. If acceptance fails: stop, fix, re-verify, then continue.
5. No silent fallback is allowed in code changes.

## Milestones

### M0 Baseline Freeze
Status: pending

Outputs:
- Baseline architecture note of current result-page flow.
- Inventory of risky coupling points (render path, schema fallback, style overlap).

Acceptance:
- Baseline document in `documentation.md` completed.
- Explicit refactor boundary and rollback point recorded.

Verification:
- `rg -n "renderIntegratedFeature|result_shell_overrides|table_title|columns|rows" ui/pages/detection_page_assets core/execution -S`

---

### M1 ResultView Contract Freeze (v2)
Status: pending

Outputs:
- Canonical ResultView field contract for frontend consumption.
- Contract policy: missing required fields => explicit error path.

Acceptance:
- Contract documented in `documentation.md`.
- Backward fallback references for removed fields identified and queued for removal.

Verification:
- `rg -n "table_title|table_subtitle|columns|rows|chart\\]" core/execution ui/pages/detection_page_assets -S`

---

### M2 Backend Unified Output Path
Status: pending

Outputs:
- All result builders normalized through single view-building path.
- Contract-compliant output from `get_results_for_execution`.

Acceptance:
- No new builder bypasses contract normalizer.
- Error messages remain explicit and user-readable.

Verification:
- `rg -n "get_results_for_execution|build_single_tool_view|normalize_result_view" core/execution -S`

---

### M3 Frontend Single Rendering Path
Status: pending

Outputs:
- One integrated renderer entry path.
- Remove runtime monkey-patch override behavior.

Acceptance:
- History-open and workflow-open both go through same renderer.
- No global override of core renderer functions remains.

Verification:
- `rg -n "result_shell_overrides|global\\.renderIntegratedFeature|global\\.renderIntegratedTable|global\\.renderIntegratedChart" ui/pages/detection_page_assets -S`

---

### M4 Information Architecture Reorder
Status: pending

Outputs:
- Fixed section order:
  1) Overview
  2) Core Result
  3) Files
  4) Diagnostics

Acceptance:
- Default landing on core result for completed history execution.
- Diagnostics always displays execution identity and key provenance.

Verification:
- `rg -n "execution_id|tool_version|remote_result_dir|local_result_dir|provenance" ui/pages/detection_page_assets -S`

---

### M5 History/State Stability
Status: pending

Outputs:
- Deterministic open/pin/close behavior and active-view transitions.

Acceptance:
- Reopening same execution is idempotent.
- Closing active history result always picks deterministic next target.

Verification:
- `node -e "require('./ui/pages/detection_page_assets/results/open_results_state.js')"`
- `rg -n "open_results_state|setPinned|setActive|closeResult" ui/pages/detection_page_assets/results -S`

---

### M6 Style Layer De-duplication
Status: pending

Outputs:
- Style ownership split by concern (`base/layout/report/history` style responsibilities).
- Remove duplicate selector definitions across report-related styles.

Acceptance:
- No conflicting duplicate blocks for critical integrated shell selectors.

Verification:
- `rg -n "^\\.integrated-shell|^\\.integrated-sidebar|#integrated-title|#integrated-subtitle" ui/pages/detection_page_assets/*.css -S`

---

### M7 Test/Checks Completion (User-Executed pytest)
Status: pending

Outputs:
- Updated test list for contract and rendering regression coverage.
- Manual check list for user to run in local environment.

Acceptance:
- All required checks documented with expected outcomes.
- No test weakening.

Verification:
- `rg -n "result|workbench|history|view|schema" tests -S`

---

### M8 Cleanup and Dead-Code Removal
Status: pending

Outputs:
- Remove obsolete fields, adapters, and dead modules introduced by old path.

Acceptance:
- No references remain to deleted contract fields.
- No stale bridge between old and new renderer paths.

Verification:
- `rg -n "legacy|fallback|deprecated|table_title|table_subtitle|global\\." ui/pages/detection_page_assets core/execution -S`

---

### M9 Release Gate
Status: pending

Outputs:
- Release checklist with rollback steps.
- Final summary in `documentation.md`.

Acceptance:
- Checklist signed off.
- Last milestone status marked completed with known residual risks.

Verification:
- Manual checklist review in `documentation.md`.

## Dependency Order
M0 -> M1 -> M2 -> M3 -> M4 -> M5 -> M6 -> M7 -> M8 -> M9

## Stop Conditions
- Any regression that breaks result-page core interaction.
- Any schema mismatch discovered in history result opening path.
- Any requirement conflict with repository hard constraints.

## Risk Register
1. Hidden coupling between `result_shell_overrides.js` and runtime globals.
2. Schema migration may expose unhandled edge cases in older execution records.
3. Style de-dup may accidentally affect non-result tabs if selector boundaries are weak.
