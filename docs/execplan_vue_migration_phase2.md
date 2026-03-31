# H2OMeta Vue Migration ExecPlan: Phase 2

## Goal

Phase 2 migrates low-risk, read-only regions into the Vue shell while keeping
all write actions and the full result renderer on the legacy path.

## In Scope

- top-level tab state
- inline notice presentation
- execution history list and search
- integrated workbench feature list
- read-only workbench summary panel for the selected feature

## Out of Scope

- tool form submission
- descriptor-driven parameter editors
- database scan flows
- result chart / table / HTML renderer migration
- changing Python slot names or payload structure

## Frozen Interfaces

The following must remain unchanged in Phase 2:

- QWebChannel object name: `bridge`
- `window._onRunResult`
- `window._onExecutionUpdate`
- Python slots:
  - `get_execution_history`
  - `get_integrated_workbench_config`
  - `run_tool`
  - `get_results_for_execution`

## Deliverables

- Vue read-only shell with:
  - history search and record list
  - integrated feature sidebar
  - simple feature detail summary
  - completed execution preview metadata loaded through
    `get_results_for_execution()`
- bridge wrappers for history and workbench config loading
- store ownership for history state, notice state, and workbench selection
- callback-driven shell refresh after `window._onRunResult` and
  `window._onExecutionUpdate`

## Validation

Phase 2 is only complete if:

- history records can be loaded through the existing bridge
- workbench config can be loaded through the existing bridge
- selecting a history record updates Vue state without mutating Python payloads
- selecting a feature updates Vue state without touching the legacy result
  renderer contract
- callback compatibility remains intact
- run/complete callbacks can refresh history and workbench state without
  renaming any callback entrypoint
- completed executions can hydrate a read-only workbench preview without taking
  ownership of the full legacy result renderer

## Rollback

Phase 2 remains behind the built Vue entrypoint. If the Vue shell is not built
or needs to be rolled back, the host falls through to the legacy
`index_galaxy.html` path.
