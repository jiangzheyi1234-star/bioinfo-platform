# Result Page Refactor Prompt

## Goal
Refactor the Detection "结果工作台" into a stable, contract-driven, and maintainable result page that is predictable for users and deterministic for engineering iteration.

## Why Now
Current result-page behavior is hard to evolve safely because rendering logic, view-model fallbacks, and style layers evolved in parallel. We need a long-horizon execution plan that can run milestone-by-milestone without scope drift.

## Scope
- Detection integrated result page and its result data contract path:
  - `core/execution/tool_bridge_*`
  - `core/execution/single_tool_view_*`
  - `ui/pages/detection_page_assets/*` (integrated/history/result-related modules)

## Out Of Scope
- Non-result tabs that are unrelated to result rendering behavior.
- Rewriting remote execution orchestration.
- Any "test-environment hacks" to force green tests.

## Success Criteria
1. Single rendering path for integrated result view.
2. Single explicit ResultView contract (no silent fallback, no deleted-field back references).
3. Information architecture becomes consistent:
   - overview -> core result -> files -> diagnostics.
4. Large-file decomposition follows repo rule (>600 lines prefers extraction).
5. Every milestone has acceptance criteria and rollback-safe commits.

## Hard Constraints (from repository rules)
- Fail loudly. No silent fallback.
- Do not keep references to deleted fields.
- For files > 600 lines, prefer extraction over piling more logic.
- `pytest` execution is user-owned in this environment; agent does not run pytest here.
- Do not weaken tests or product behavior to fit a broken test environment.

## Long-Horizon Execution Method
Use the 4-doc loop and keep it as the sole source of truth for this task:
1. `prompt.md`: objective and boundaries
2. `plan.md`: milestones and acceptance
3. `implement.md`: execution runbook and guardrails
4. `documentation.md`: living status, decisions, and risks

Execution loop per milestone:
Plan -> Edit -> Run tools -> Observe -> Repair -> Update docs -> Repeat.

## References
- OpenAI blog: Run long-horizon tasks with Codex  
  https://developers.openai.com/blog/run-long-horizon-tasks-with-codex
- Design-desk example docs:
  - https://github.com/derrickchoi-openai/design-desk/blob/main/docs/prompt.md
  - https://github.com/derrickchoi-openai/design-desk/blob/main/docs/plans.md
  - https://github.com/derrickchoi-openai/design-desk/blob/main/docs/implement.md
  - https://github.com/derrickchoi-openai/design-desk/blob/main/docs/documentation.md
