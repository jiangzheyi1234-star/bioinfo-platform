# H2OMeta Vue Migration ExecPlan: Harness Coordination

## Summary

This document defines the long-running harness process for the `Vite + Vue 3`
migration. The goal is to prevent scope drift during a large frontend rewrite by
splitting responsibility across three roles:

- Main Agent: planner and integrator
- Frontend Agent: Vue/Vite generator
- Compatibility Agent: bridge and runtime evaluator

The harness is intentionally process-oriented: each phase needs a contract,
implementation, evaluation, and structured handoff before the next phase may
start.

## Roles

### Main Agent

Owns the migration plan and the only authoritative phase contract.

Responsibilities:

- write and maintain `docs/execplan_vue_migration_*.md`
- freeze the phase boundary and allowed changes
- merge reports from the other agents
- decide whether a phase is complete
- prevent scope creep and unplanned interface drift

### Frontend Agent

Owns the Vue/Vite implementation path.

Responsibilities:

- create the Vue scaffold
- split the current `app_galaxy.js` responsibilities into modules
- move command-style DOM logic into Vue state and components
- keep the Python payload contract unchanged

### Compatibility Agent

Owns host, bridge, and regression safety.

Responsibilities:

- verify Qt host loading
- verify QWebChannel initialization
- verify `bridge` object exposure
- verify `window._onRunResult` and `window._onExecutionUpdate`
- verify the execution/result path still works after each phase

## Harness Loop

Each phase must follow the same loop:

1. Main Agent writes the phase contract
2. Frontend Agent implements only the contracted scope
3. Compatibility Agent evaluates the phase against frozen interfaces
4. Main Agent resolves failures and decides whether to continue
5. A handoff note is written before the next phase begins

Hard rule:

- no phase may begin without a contract
- no phase may advance without evaluator sign-off
- no phase may silently widen its scope

## Phase Contracts

### Phase 0: Freeze

Purpose:

- define the exact boundaries that must not move
- document current runtime ownership

Artifacts:

- frozen interface list
- rollback path
- current host entry path

### Phase 1: Vue Host Scaffold

Purpose:

- prove that a local Vue build can be loaded by the existing Qt host
- prove the bridge still initializes and callbacks still flow

Artifacts:

- buildable Vue scaffold
- build output path
- fallback entry behavior

### Phase 2: Read-only Blocks

Purpose:

- move low-risk display regions first
- keep business actions on the old path until verified

Artifacts:

- migrated read-only block list
- still-legacy block list

### Phase 3: Tool Form

Purpose:

- migrate tool list, descriptors, parameters, and run entry
- keep `run_tool()` contract stable

Artifacts:

- form mapping
- parameter contract notes

### Phase 4: Result Workspace

Purpose:

- migrate integrated result rendering
- keep `get_results_for_execution()` payload shape stable

Artifacts:

- result component mapping
- archetype coverage notes

### Phase 5: Cleanup

Purpose:

- remove old imperative code after the Vue path fully owns the page

Artifacts:

- removal list
- final rollback note

## Evaluation Criteria

The Compatibility Agent must verify these every phase:

- Qt can load the active frontend entry
- QWebChannel can register `bridge`
- `run_tool()` still works
- `window._onRunResult` still works
- `window._onExecutionUpdate` still works
- history loading still works
- result opening still works

Phase-specific checks:

- Phase 1: build output loads and bridge connects
- Phase 2: navigation and read-only displays remain correct
- Phase 3: form submission payloads remain stable
- Phase 4: summary / table / charts / sections / artifacts still render
- Phase 5: old logic removal does not break bootstrapping

## Handoff Rules

Each phase handoff must state:

- what was completed
- what remains risky
- what the next phase starts with
- how to roll back

The handoff is part of the harness. If it is missing, the phase is not done.

## Failure Rules

The following are immediate phase failures:

- bridge name changes
- payload shape changes
- callback loss
- result page no longer loads
- duplicate ownership of the same UI region without a clear handoff

If any of the above happens, the phase must stop and roll back to the last
known-good entry.
