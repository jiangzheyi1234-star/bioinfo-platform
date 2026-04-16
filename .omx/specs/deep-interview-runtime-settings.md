# Deep Interview Runtime Settings — approved one-click configuration contract

## Status
- Source of truth for the current approved runtime-settings implementation lane.
- Captures the latest user-approved logic that must be implemented directly without re-planning product direction.
- Intended to align backend/runtime semantics, frontend one-click flow, and verification.

## Scope
This spec freezes the runtime-configuration behavior for the SSH workbench “一键配置 Runtime” flow and the persisted runtime settings used by later workflow execution.

It governs:
- configuration-time detection/orchestration logic
- direct-execution UI flow
- remediation behavior
- persisted runtime path semantics
- runtime launch environment semantics

It does **not** re-open product planning, backend selection strategy, or the domain model.

## Frozen product decisions
1. One-click runtime configuration is a **direct execution flow**.
2. Clicking one-click configuration enters execution immediately.
3. There is **no upfront consolidated confirmation card** before execution starts.
4. There are **no per-path interruptive confirmation popups**.
5. Candidate-selection UI may interrupt **only** when a step finds multiple compliant Java or Nextflow paths.
6. If multiple compliant Nextflow paths are detected, the UI may allow one selection and must persist it.
7. Java / Nextflow / Docker remediation must be **terminal-mediated**.
8. Remediation commands must be sent **sequentially**, not batched.
9. “Command sent” is **not** success; explicit re-verification is required after terminal remediation.
10. There is **no silent background install or upgrade**.

## Runtime requirements

### Configuration-time detection
1. Configuration-time Java detection must **not** depend on `NXF_JAVA_HOME`.
2. `NXF_JAVA_HOME` is **not** the primary Java detector during configuration.
3. Configuration-time detection must resolve concrete Java and Nextflow candidates using real executable paths and compliance checks.
4. Minimum runnable Nextflow version is **25.04.0**.
5. Recommended Nextflow version is **26.04.0+**.
6. `NXF_AGENT_MODE` may be enabled **only when Nextflow >= 26.04.0**.
7. Docker readiness must be checked explicitly.
8. Conda is non-required and must not block one-click configuration.
9. Conda must not be reintroduced as a required dependency.

### Candidate selection
1. The default path is non-interruptive automatic detection.
2. Only if a detection step finds **multiple compliant candidates** may the UI ask the user to choose.
3. If exactly one compliant Java or Nextflow path exists, it must be selected automatically.
4. If a chosen Nextflow path is persisted, later execution must keep using that fixed path until reconfigured.

### Persistence semantics
1. Runtime paths must be **fixed and persisted** after successful configuration.
2. Saved runtime execution must **not depend on PATH drift**.
3. Saved runtime execution must **not reintroduce PATH or conda fallback assumptions**.
4. Pipeline repository paths and project runtime directories must remain separate.

### Runtime execution semantics
1. `NXF_JAVA_HOME` is only a **post-save runtime binding**.
2. During actual runtime execution, use **only `NXF_JAVA_HOME`**, not `JAVA_HOME`.
3. The saved runtime record must carry the resolved executable paths and launcher semantics needed for non-interactive execution.
4. Docker is the required execution backend for future execution-oriented tasks.
5. No host-mode comeback.

## UI flow contract
1. The one-click wizard keeps the flow grouped as:
   - 检测环境
   - 准备 Runtime
   - 完成
2. The UI must not regress to a manual strategy-selection or decision-card flow.
3. The UI must not use browser-native interruptive dialogs for routine path confirmation.
4. The UI may expose remediation actions, but those actions only send commands to the terminal and then require the user to re-check.
5. The UI must make it clear that:
   - command sent ≠ repair complete
   - re-verification is required
   - Conda is optional fallback only, not a blocker

## Domain and architecture boundaries
1. Keep **Project -> Task** as the domain model.
2. Keep one backend lane for:
   - configuration-time detection/orchestration logic
   - persisted runtime config semantics
3. Keep one frontend lane for:
   - direct execution UI flow
   - dynamic remediation steps
4. Keep one verification lane for:
   - contract tests
   - status semantics
   - exact PASS/FAIL evidence
5. Do not re-plan product direction inside implementation work.
6. Follow the latest user-approved logic exactly.

## Acceptance criteria
- Clicking “一键配置 Runtime” starts the flow directly without an upfront summary/confirmation card.
- The UI does not show per-path confirmation popups during normal single-candidate detection.
- The UI asks the user to choose only when multiple compliant Java or Nextflow candidates exist.
- Java detection during configuration succeeds or fails independently of `NXF_JAVA_HOME`.
- Persisted runtime settings store fixed Java/Nextflow execution semantics for later runs.
- Saved execution uses `NXF_JAVA_HOME` only, not `JAVA_HOME`.
- Saved execution does not rely on PATH drift or conda auto-activation.
- Nextflow < 25.04.0 is rejected as non-runnable.
- Nextflow 25.04.x–26.03.x may run but must keep `NXF_AGENT_MODE` off.
- Nextflow >= 26.04.0 may enable `NXF_AGENT_MODE`.
- Java / Nextflow / Docker remediation is terminal-mediated, sequential, and followed by explicit re-verification.
- Docker readiness is checked explicitly.
- Conda remains optional and non-blocking.
- No silent install/upgrade path is introduced.

## Implementation anchors
- Frontend:
  - `apps/web/app/components/prepare-server-wizard.tsx`
  - `apps/web/app/components/ssh-shell.tsx`
  - `apps/web/app/components/runtime-inspection.ts`
- Backend/runtime:
  - `core/remote/runtime_resolution.py`
  - `core/app_runtime/workbench_runtime_ops.py`
  - `core/app_runtime/workflow_runtime_ops.py`
  - `core/workflow/runtime_ops.py`
- Verification:
  - `apps/web/app/components/prepare-server-wizard.contract.test.ts`
  - `tests/test_runtime_resolution.py`
  - runtime launcher / resolved-state tests covering persisted execution semantics

## Non-goals
- Reintroducing conda as a required prerequisite
- Reintroducing host-mode execution
- Allowing saved runtime execution to fall back to ambient PATH / shell activation
- Adding silent automatic install or upgrade flows
- Re-opening product planning or alternate UX directions in this implementation lane

## Deliverable expectations
- Backend lane reports changed files and runtime-detection semantics.
- Frontend lane reports UI flow changes and remediation behavior.
- Verification lane reports exact PASS/FAIL evidence and remaining gaps.
- Final integration output includes risks and exact verification evidence.
