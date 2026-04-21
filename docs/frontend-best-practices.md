# H2OMeta Frontend Best Practices

**Status:** Canonical frontend principles  
**Date:** 2026-04-21

> This document is the authoritative frontend principles document for v1.
> If older frontend notes conflict with this document, this document wins.

## 1. Product Model

H2OMeta is a **workspace-style, object-driven workbench**, not:

- a tab-centric desktop utility
- an IDE
- a file browser
- a chat-first app

The product model is:

- stable sidebar navigation
- route-driven object pages
- local detail tabs inside a single object
- optional convenience layers later, not as the primary structure

## 2. Primary Reference Stack

### Product / IA

- **Linear** for object pages, workflow-first interaction, status density
- **Notion** for workspace navigation and page-as-object thinking
- **AppFlowy** for open-source workspace IA inspiration

### Code organization

- **Bulletproof React** for feature-first frontend structure
- **Next.js App Router** for route-first UI architecture and server/client boundaries
- **Patterns.dev** for component composition and rendering patterns

### Components / accessibility

- **Radix UI / shadcn/ui** for accessible primitives and interaction boundaries

### State and data

- **TanStack Query mindset** for server-state, polling, and caching discipline

### Visual system

- **Refactoring UI** for spacing, hierarchy, and restrained visual language

### Performance and platform

- **web.dev** and **MDN** for large-list performance, file preview limits, and browser-native APIs

## 3. Navigation Rules

### 3.1 Sidebar is the primary navigation

Primary v1 navigation:

- Home
- Servers
- Projects
- Runs
- Results
- Settings

### 3.2 Route = main object context

Main context is established by route, not by tabs.

Examples:

- `/servers/[serverId]`
- `/projects/[projectId]`
- `/runs/[runId]`
- `/results/[resultId]`

### 3.3 Tabs are local only

Tabs are only for parallel views **within a single object**.

Good:

- `Run Detail`: Overview / Events / Logs / Outputs / Spec
- `Result Detail`: Overview / Files / Preview / Metadata / Raw JSON

Bad:

- using tabs as the app’s primary navigation
- using tabs as a substitute for compare mode

## 4. Layout Rules

Use a workspace shell:

- left sidebar = global navigation
- center = page content
- right side = optional context panel
- bottom dock = debug terminal only

The terminal is a debugging/ops surface, not the main workflow surface.
The UI should not depend on remote shell details for normal operation; it should rely on local-backend object APIs and server health state.

## 5. Page Design Rules

### 5.1 Pages are object-first

Primary entities become pages:

- Server
- Project
- Run
- Result

### 5.2 Header outside tabs

Important identity and action content must appear above tabs:

- breadcrumb
- page title
- key actions
- summary strip / key facts

### 5.3 Lists and details

Use:

- list pages for discovery
- detail pages for deep work

Do not overload list pages with too many inline editors or modal flows.

## 6. Tabs Rules

### 6.1 When tabs are appropriate

Use tabs when:

- content belongs to the same object
- tabs represent sibling information views
- the user only needs one view at a time

### 6.2 When tabs are not appropriate

Do not use tabs for:

- primary app navigation
- side-by-side comparison
- hiding critical first-read content

### 6.3 Tabs activation

Where tab switching may trigger loading or visible latency, prefer **manual activation**.

### 6.4 Tab count

Keep tab count within roughly 4–6 per object page.

### 6.5 Tab state

Tab state should be URL-addressable where useful:

- `?tab=logs`
- `?tab=preview&artifact=art_003`

## 7. Compare vs Switch

### Switch

Use tabs or an open-items convenience strip for switching between objects.

### Compare

Use a dedicated compare view / split view when users need to inspect two results or objects at the same time.

Tabs are not compare mode.

## 8. Result Preview Rules

### 8.1 Preview is artifact-specific

Preview must clearly identify which artifact is being previewed.

### 8.2 v1 selector style

Use a top **searchable artifact selector** in Preview tab by default.

Reason:

- more restrained
- avoids duplicating the Files tab
- better aligned with the current object-page design

### 8.3 Escalation rule

If previewable artifact counts grow large and users switch among them frequently, upgrade to a dedicated preview sidebar later.

### 8.4 Preview modes

Support renderer-by-type:

- image preview
- text preview
- light table preview for CSV/TSV
- unsupported fallback with download

### 8.5 Preview limits

Preview must be capped:

- large text: preview a bounded number of lines
- large tables: preview only a bounded number of rows
- large images/files: avoid unbounded eager loading

## 9. State Management Rules

### 9.1 Separate server state from UI state

Server state examples:

- run status
- run events
- logs
- result detail
- server health

UI state examples:

- active tab
- selected artifact
- pane open/close
- local sort/filter state

Do not mix them.

### 9.2 Server-state mindset

Design hooks and API layers with a TanStack Query-compatible mental model even if TanStack Query is introduced later.

### 9.3 Polling

Polling belongs to server-state handling, not scattered component local timers.

## 10. Server / Client Boundary Rules

Use Next.js App Router best practices:

- server-first for initial page data where practical
- client components only where interaction is required
- push client logic down to leaf components

## 11. Code Organization Rules

Favor feature-based structure over a single shared component bucket.

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
    api/
    components/
    hooks/
    model/
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

### Rules

- `components/ui`: reusable presentation primitives only
- `components/layout`: shell and generic layout pieces only
- `features/*`: business-specific UI, hooks, API bindings, models

## 12. Error Handling Rules

Frontend must understand structured backend errors.

Every significant error UI should preserve:

- title
- detail
- code
- `requestId`

Use:

- toast for short-lived success/failure notices
- inline error cards for page-blocking or resource-specific failures

## 13. Visual Rules

### 13.1 Visual hierarchy

Use:

- spacing
- typography
- muted color

before using extra borders, badges, or heavy color blocks.

### 13.2 Density

- list pages: moderately dense
- detail pages: lower density, better breathing room

### 13.3 Color usage

- neutral base palette
- restrained accent usage
- status colors only where they carry semantic meaning

## 14. Motion Rules

- minimal motion
- no decorative heavy transitions
- subtle layout transitions only when they improve orientation
- respect reduced motion preferences

## 15. Performance Rules

- do not eagerly render heavy tab panels
- lazy fetch heavy previews
- cap preview size
- prepare for virtualization where lists may become large
- prefer browser-native download/upload flows where possible

## 16. v1 UX Scope Rules

v1 should stay restrained:

- no global business tabs as primary navigation
- no block editor
- no AI copilot sidecar as core UI
- no generalized multi-view database abstraction
- no complex compare system unless real usage justifies it
