# H2OMeta Local API

## Run
```bash
python3 -m apps.api.run
```

Default bind:
- host: `127.0.0.1`
- port: `8765`

## Main endpoints
- `GET /health`
- `GET /api/v1/tools`
- `GET /api/v1/tools/{tool_id}/descriptor`
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
- `GET /api/v1/projects/{project_id}/workbench/tools`
- `GET /api/v1/projects/{project_id}/workbench/config`
- `GET /api/v1/projects/{project_id}/workbench/history`
- `GET /api/v1/projects/{project_id}/workbench/configured-databases`
- `GET /api/v1/projects/{project_id}/workbench/executions/{execution_id}/result`
- `DELETE /api/v1/projects/{project_id}/workbench/executions/{execution_id}`
- `GET /api/v1/projects/{project_id}/workbench/executions/{execution_id}/remote-status`
- `GET /api/v1/projects/{project_id}/workbench/primer-results`
- `GET /api/v1/projects/{project_id}/executions`
- `GET /api/v1/projects/{project_id}/executions/{execution_id}`
- `GET /api/v1/projects/{project_id}/history`
- `POST /api/v1/projects/{project_id}/executions/{execution_id}/archive`
- `POST /api/v1/executions`
- `POST /api/v1/workbench/run`
- `GET /api/v1/logs/app`
- `GET /api/v1/events/executions`
