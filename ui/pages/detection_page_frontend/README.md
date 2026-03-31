# H2OMeta Detection Frontend (Phase 1 / Phase 2)

This directory contains the Vite + Vue 3 scaffold for the long-running
harness migration of the detection page.

## Current Scope

Phase 1 proves that:

- Qt can load a built Vue entrypoint
- QWebChannel can initialize
- the existing `bridge` object is visible
- Python callbacks can still reach the frontend

Phase 2 starts the first read-only ownership transfer:

- top tab state
- inline notice area
- execution history list
- integrated workbench feature sidebar
- simple read-only feature preview

The Vue shell still does **not** replace the legacy write paths or the full
result renderer.

## Build Output

`vite build` writes to:

`ui/pages/detection_page_assets/dist/`

The Qt host prefers `dist/index.html` when it exists and otherwise falls back
to the legacy `index_galaxy.html`.

## Commands

```bash
npm install
npm run build
```

## Frozen Contract

- `bridge` object name must not change
- `window._onRunResult` must remain available
- `window._onExecutionUpdate` must remain available
- Python host slots and payload shape remain unchanged during Phase 1 / Phase 2
