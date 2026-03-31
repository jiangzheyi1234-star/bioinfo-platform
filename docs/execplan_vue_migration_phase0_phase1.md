# H2OMeta Vue Migration ExecPlan: Phase 0 / Phase 1

## Scope

This document is the baseline contract for the `Vite + Vue 3` migration of the
detection page. It covers:

- Phase 0: freeze host and bridge boundaries
- Phase 1: establish a Vue/Vite host shell that can be loaded by the existing
  Qt detection page

## Frozen Interfaces

The following interfaces are frozen during Phase 0 and Phase 1:

- Qt host file: `ui/pages/detection_page_web.py`
- host container: `ui/widgets/web_ui_host.py`
- QWebChannel object name: `bridge`
- callback entrypoints:
  - `window._onRunResult`
  - `window._onExecutionUpdate`
- Python execution chain:
  - `ToolBridgeService -> ToolEngine -> ServiceLocator -> JobDispatcher`

No Phase 0 / Phase 1 work may rename, reshape, or silently replace these
interfaces.

## Phase 0 Deliverables

- baseline host and bridge contract written down
- dist-first host entry resolution with legacy fallback
- rollback path documented

## Phase 1 Deliverables

- Vue/Vite frontend scaffold under `ui/pages/detection_page_frontend/`
- build output path targeting `ui/pages/detection_page_assets/dist/`
- Qt host preferring `dist/index.html` and falling back to `index_galaxy.html`
- minimal bridge bootstrap proving `bridge`, `window._onRunResult`, and
  `window._onExecutionUpdate` can still be attached

## Validation

Phase 0 / Phase 1 are considered complete only if:

- `detection_page_web.py` can still compile
- the Qt host can resolve an HTML entrypoint
- the bridge bootstrap preserves `bridge`
- callbacks remain present on `window`
- legacy fallback remains available when `dist/index.html` does not exist

## Rollback

Rollback is performed by deleting or ignoring
`ui/pages/detection_page_assets/dist/index.html`. The Qt host will then load
`ui/pages/detection_page_assets/index_galaxy.html` again without changing the
Python bridge layer.
