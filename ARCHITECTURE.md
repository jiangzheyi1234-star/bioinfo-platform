# H2OMeta Architecture (2026-04)

> **Authority note:** this file summarizes repository state and migration context.
> The canonical target architecture now lives in:
>
> - `docs/backend-contract-v1.md`
> - `docs/frontend-best-practices.md`
> - `docs/frontend-plan-v1.md`
>
> If this file conflicts with those documents, the docs under `docs/` win.

## Current Stack

- Desktop shell: Tauri (Rust)
- Desktop UI: Next.js App Router (apps/web)
- Local backend: FastAPI (apps/api)
- Runtime core: pure Python services (core/), no PyQt runtime dependency
- Remote execution: SSH + screen + conda

## Runtime Flow

1. Web/Tauri UI submits tool runs to FastAPI.
2. API delegates to `core.app_runtime.RuntimeService`.
3. `ServiceLocator` wires execution services (`ToolEngine`, `ExecutionPreparer`, `JobDispatcher`, `JobQueue`).
4. Remote commands run on target host via `SSHService.run()` single queue.
5. Status and artifacts are persisted in project SQLite and exposed through API endpoints.

## Project Boundaries

- `apps/web`: all user-facing UI and interaction state.
- `apps/desktop`: Tauri launcher and health-check guarded startup.
- `apps/api`: FastAPI routes and schema layer.
- `core/`: execution, data, remote, pipeline, environment runtime logic.
- `plugins/`: tool descriptors in YAML.

## Key Constraints

- No direct Paramiko `exec_command()` calls in app logic. Use `SSHService.run()`.
- Persisted execution status remains: `pending`, `running`, `completed`, `failed`, `retrying`.
- Long running remote tasks must run detached on remote side.
- Legacy PyQt UI path has been removed from active architecture.

## Migration Outcome

- Default entry is Tauri desktop shell (`run.bat`).
- Legacy `ui/` PyQt application code is removed from repository runtime path.
- No PyQt compatibility adapter remains in the active runtime path.
