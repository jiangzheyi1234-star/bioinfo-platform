# H2OMeta Local API

> **Authority note:** this README reflects the current route surface in `apps/api/main.py`.
> The canonical v1 target backend contract lives in `docs/backend-contract-v1.md`.
> If this README conflicts with that document, `docs/backend-contract-v1.md` wins.

## Run
```bash
python3 -m apps.api.run
```

Default bind:
- host: `127.0.0.1`
- port: `8765`

## Current endpoint groups

### Health and runtime metadata
- `GET /health`
- `GET /api/v1/version`

### Settings
- `GET /api/v1/settings`
- `PUT /api/v1/settings`

### SSH connection
- `GET /api/v1/ssh/status`
- `POST /api/v1/ssh/connect`
- `POST /api/v1/ssh/disconnect`
- `POST /api/v1/ssh/test`

### SSH terminal sessions
- `POST /api/v1/ssh/terminal/sessions`
- `DELETE /api/v1/ssh/terminal/sessions/{session_id}`
- `WS /api/v1/ssh/terminal/sessions/{session_id}/stream`

### Projects
- `GET /api/v1/projects`
- `GET /api/v1/projects/current`
- `POST /api/v1/projects`
- `PATCH /api/v1/projects/{project_id}`
- `POST /api/v1/projects/{project_id}/archive`
- `POST /api/v1/projects/{project_id}/restore`
- `DELETE /api/v1/projects/{project_id}`
- `POST /api/v1/projects/{project_id}/open`

## Note

Older task/workflow/run endpoint docs were removed because they no longer matched `apps/api/main.py`.
Use the route declarations in `apps/api/main.py` as the source of truth when adding or changing API surfaces.
