# H2OMeta Frontend Plan v1

**Status:** Canonical frontend implementation plan  
**Date:** 2026-04-21

> This document is the authoritative frontend implementation plan for v1.
> If older UI notes conflict with this document, this document wins.
> Approved visual and interaction scheme: `docs/ui-scheme-v1.1.md`

## 1. Purpose

Translate the canonical backend contract into a restrained, workspace-style UI aligned with:

- Sidebar + Route + Object Page
- local tabs inside object detail pages
- result/run first workflows
- local backend as the only API target

## 2. Current Repository Baseline

Current frontend code is centered around:

- SSH connection dialog
- SSH terminal dock
- remote environment checks
- settings placeholder

This is a useful shell baseline but not yet the target product IA.

## 3. Target Navigation

Primary sidebar navigation:

- Home
- Servers
- Projects
- Runs
- Results
- Settings

## 4. Target Routes

- `/` -> Home
- `/servers` -> Servers list
- `/servers/[serverId]` -> Server detail
- `/projects` -> Projects list
- `/projects/[projectId]` -> Project detail
- `/projects/[projectId]/new-run` -> New Run
- `/runs` -> Runs list
- `/runs/[runId]` -> Run detail
- `/results` -> Results list
- `/results/[resultId]` -> Result detail
- `/settings` -> Settings

## 5. Shell Model

Keep and evolve the current shell rather than rewriting from scratch.

### Keep

- top-level `AppShell`
- bottom terminal dock
- current use of shadcn/Radix-style primitives

### Change

- convert SSH-shell mindset into workspace-shell mindset
- replace global tab-strip as the primary shell model
- use route/page header instead of top-level content tabs

## 6. Page Definitions

### 6.1 Home

Purpose:

- recent runs
- server readiness summary
- recent results
- quick actions

### 6.2 Servers

#### Servers list

Shows:

- server identity
- readiness status
- reason code
- latest health snapshot

#### Server detail

Shows:

- overview
- health
- security/trust info
- bootstrap and management actions

### 6.3 Projects

#### Projects list

Project discovery and creation.

#### Project detail

Shows:

- project overview
- inputs/uploads
- samples
- project runs
- quick start for new run

### 6.4 New Run

Structured run submission flow:

- choose server
- choose project and inputs
- choose pipeline
- review runSpec summary
- review raw runSpec
- submit and redirect to run detail

### 6.5 Runs

#### Runs list

Filterable list with:

- runId
- server
- project
- pipeline
- status
- stage
- stateVersion
- time fields

#### Run detail

Tabs:

- Overview
- Events
- Logs
- Outputs
- Spec

### 6.6 Results

#### Results list

Primary result discovery view.

#### Result detail

Tabs:

- Overview
- Files
- Preview
- Metadata
- Raw JSON

## 7. Result Detail Structure

### Header

- breadcrumb
- result title
- result actions
- source run shortcut

### Summary strip

- source run
- pipeline
- produced time
- artifact count / result dir

### Tabs

- `overview`
- `files`
- `preview`
- `metadata`
- `raw-json`

### Preview tab

- top searchable artifact selector
- preview renderer by artifact type
- bounded preview sizes
- fallback for unsupported file types

### URL state

- `?tab=preview`
- `?artifact=art_003`

## 8. Run Detail Structure

### Header

- breadcrumb
- run title / runId
- status badge
- source project/server
- actions

### Summary strip

- pipeline
- stage
- stateVersion
- start/finish
- requestId

### Tabs

- `overview`
- `events`
- `logs`
- `outputs`
- `spec`

### URL state

- `?tab=logs`
- `?stream=stderr` when useful

## 9. API Mapping

GUI talks only to local backend.

### Servers

- `GET /api/v1/servers`
- `GET /api/v1/servers/{serverId}`
- `GET /api/v1/servers/{serverId}/health`
- management actions as defined by backend contract

### Projects

- current/future project endpoints

### Runs

- `POST /api/v1/runs`
- `GET /api/v1/runs/{runId}`
- `GET /api/v1/runs/{runId}/events`
- `GET /api/v1/runs/{runId}/logs`
- `GET /api/v1/runs/{runId}/results`

### Results

- result aggregate endpoint or derived completed-run result list
- result detail and artifact preview/download routes

## 10. Data and State Plan

### 10.1 Server state

Will include:

- server health
- run status
- events
- logs
- results

### 10.2 UI state

Will include:

- active tabs
- selected artifact
- sort/filter
- panel open/close state

### 10.3 Polling

Run and server health views must be designed with centralized polling behavior in mind, ready for TanStack Query-style refetch orchestration.

## 11. Code Organization Direction

Move from generic `app/components` sprawl toward feature-based organization.

Recommended direction:

```text
app/
  (workspace)/
    servers/
    projects/
    runs/
    results/
    settings/
features/
  servers/
  projects/
  runs/
  results/
components/
  ui/
  layout/
lib/
  api/
  utils/
```

## 12. Phased Implementation Order

### Phase 1: Shell authority

- create workspace shell model
- expand sidebar to target navigation
- keep terminal dock as debug tool
- remove top-level tab-strip as main navigation model

### Phase 2: API client authority

- upgrade local API client to understand structured errors
- preserve `code`, `requestId`, headers like `Location` / `Retry-After`
- introduce resource-specific API clients

### Phase 3: Servers

- servers list
- server detail
- health / trust / bootstrap surfaces

### Phase 4: Home + Projects

- home dashboard
- projects list/detail
- uploads integrated into project/new run

### Phase 5: Runs

- run submission
- runs list
- run detail with tabs

### Phase 6: Results

- results list
- result detail
- artifact preview

## 13. Immediate Refactor Targets in Current Code

Current likely migration path:

- `app_shell.tsx` -> workspace shell entry remains
- `ssh-shell.tsx` -> evolve toward workspace shell, then split
- `ssh-shell-ui.tsx` -> split into workspace sidebar + terminal panel
- `local-api-client.ts` -> evolve into richer API foundation
- legacy remote-environment logic -> fold into server health/readiness feature

## 14. Non-Goals for Frontend v1

Frontend v1 does **not** implement:

- global business tabs as primary navigation
- Notion-style block editor
- AI copilot as core layout region
- generalized database-view system
- heavy compare mode before usage justifies it
- file-browser-first experience
