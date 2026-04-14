# H2OMeta Local API

## Run
```bash
python3 -m apps.api.run
```

Default bind:
- host: `127.0.0.1`
- port: `8765`

## Canonical workbench endpoints
- `GET /api/v1/projects/{project_id}/tasks`
- `POST /api/v1/projects/{project_id}/tasks`
- `GET /api/v1/projects/{project_id}/tasks/{task_id}/workflow`
- `PUT /api/v1/projects/{project_id}/tasks/{task_id}/workflow`
- `POST /api/v1/projects/{project_id}/tasks/{task_id}/workflow/compile`
- `POST /api/v1/projects/{project_id}/tasks/{task_id}/workflow/compatibility`
- `GET /api/v1/projects/{project_id}/tasks/{task_id}/runs`
- `POST /api/v1/projects/{project_id}/tasks/{task_id}/runs`
- `GET /api/v1/projects/{project_id}/tasks/{task_id}/runs/{run_id}`
- `POST /api/v1/projects/{project_id}/tasks/{task_id}/runs/{run_id}/cancel`
- `GET /api/v1/projects/{project_id}/tasks/{task_id}/results`
- `GET /api/v1/projects/{project_id}/tasks/{task_id}/results/summary`
- `GET /api/v1/projects/{project_id}/tasks/{task_id}/results/{result_id}`
- `GET /api/v1/projects/{project_id}/tasks/{task_id}/results/{result_id}/content`
- `GET /api/v1/projects/{project_id}/tasks/{task_id}/workspace`

## Legacy compatibility endpoints
- `POST /api/v1/workflows/compile`
- `POST /api/v1/runs`
- `GET /api/v1/projects/{project_id}/runs`
- `GET /api/v1/projects/{project_id}/runs/{run_id}`
- `POST /api/v1/projects/{project_id}/runs/{run_id}/cancel`
- `GET /api/v1/projects/{project_id}/runs/{run_id}/artifacts`
- `GET /api/v1/projects/{project_id}/runs/{run_id}/resolved-config`
- `POST /api/v1/servers/{server_id}/doctor`
- `GET /health`
- `GET /api/v1/settings`
- `PUT /api/v1/settings`
- `GET /api/v1/ssh/status`
- `POST /api/v1/ssh/connect`
- `POST /api/v1/ssh/disconnect`
- `POST /api/v1/ssh/test`
- `GET /api/v1/projects`
- `POST /api/v1/projects`
- `POST /api/v1/projects/{project_id}/open`
- `GET /api/v1/projects/{project_id}/samples`
- `POST /api/v1/projects/{project_id}/samples`
- `GET /api/v1/projects/{project_id}/databases`
- `GET /api/v1/logs/app`
- `GET /api/v1/events/executions`
