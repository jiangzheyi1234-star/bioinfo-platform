# Result Page Refactor Implementation Runbook

## Operating Mode
Use this runbook with `plan.md` as the controlling checklist.

For each milestone:
1. Confirm scope and required output.
2. Make minimal focused edits.
3. Run milestone verification commands.
4. If fail: repair immediately (no carry-over failures).
5. Update `documentation.md`.
6. Commit with milestone tag.

## Repository Guardrails (Must Keep)
1. Fail loudly. No silent fallback.
2. Do not preserve deleted-field compatibility references.
3. Do not weaken tests or behavior to fit environment issues.
4. `pytest` is user-executed in this environment (agent will not run pytest here).
5. For files > 600 lines, prefer extraction to adjacent modules.

## Execution Template (Per Milestone)
Use this checklist each time:

- [ ] Read current milestone in `plan.md`
- [ ] Mark milestone status `in progress` in `documentation.md`
- [ ] Implement scoped changes only
- [ ] Run listed verification commands
- [ ] Record outcomes and residual risks
- [ ] Mark status `completed` or `blocked`
- [ ] Create commit (if milestone complete)

## Change Pattern By Layer

### Backend (Result contract)
- Prefer normalization in:
  - `core/execution/single_tool_view_builder.py`
  - `core/execution/tool_bridge_result_views.py`
- Keep `get_results_for_execution` behavior explicit:
  - missing execution -> explicit error
  - non-completed status -> explicit error

### Frontend (Integrated result)
- Keep one renderer entry path.
- Remove runtime override behavior rather than layering more conditionals.
- Prefer explicit renderer dependencies over global mutable function patching.

### Styles
- Separate ownership by concern.
- Remove duplicated selector blocks before introducing new style rules.

## Validation Commands (Safe, quick, local)
Use only milestone-relevant commands:
- `rg -n "pattern" <paths> -S`
- `node -e "require('./ui/pages/detection_page_assets/results/open_results_state.js')"`
- Additional non-pytest checks as needed.

User-owned validation:
- `pytest ...` (run by user)

## Commit Convention
Commit title format:
- `[result-page][M#] <short action>`

Commit body template:
1. Milestone: `M#`
2. Why: one paragraph
3. What changed: bullet list
4. Verification: commands + outcomes
5. Risks/next: bullet list

## Escalation / Blockers
If blocked:
1. Stop active coding.
2. Record blocker in `documentation.md` with:
   - exact symptom
   - attempted fix
   - minimum needed decision/input
3. Continue only after blocker resolution is documented.

## Done Definition (Task Level)
All are required:
1. M0-M9 completed or explicitly deferred with rationale.
2. No silent fallback on result contract path.
3. No dead references to removed result fields.
4. `documentation.md` final summary written.
