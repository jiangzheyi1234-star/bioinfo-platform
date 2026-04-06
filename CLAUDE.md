# H2OMeta Development Notes (Current)

## Product Direction

- Desktop-first pathogen analysis workbench.
- Tauri desktop shell with Next.js frontend and local FastAPI backend.
- Runtime and remote execution logic lives in `core/`.

## Architecture Rules

1. Keep UI logic in `apps/web`; backend logic in `apps/api` and `core`.
2. All remote commands must go through `SSHService.run()` queue.
3. Avoid direct DB writes outside service-layer modules.
4. New tools are registered by YAML descriptors under `plugins/`.

## Testing Notes

- Core and API tests should be independent from GUI frameworks.
- Legacy PyQt UI tests were removed with desktop migration cutover.
- Keep tests behavior-focused and deterministic.

## Local Run Shortcuts

- Desktop shell check: `run.bat --check`
- Build web: `npm --prefix apps/web run build`
- Build desktop debug shell: `npm --prefix apps/desktop run build:debug:no-bundle:win-gnu`
- Start API: `py -3 -m apps.api.run`
