# Workspace UI First Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a restrained first-pass workspace UI for the web app covering shell polish, home, runs list, and run detail scaffolding aligned to the approved Figma-ready spec.

**Architecture:** Keep the existing SSH shell provider and upgrade the presentation layer around it. Add focused workspace UI primitives plus mock-backed page compositions so the app communicates the target information architecture and backend contract before full API integration.

**Tech Stack:** Next.js App Router, React 19, TypeScript, Tailwind CSS 4, existing shadcn/Radix primitives

---

### Task 1: Add shared workspace UI primitives

**Files:**
- Create: `apps/web/app/components/workspace-primitives.tsx`
- Create: `apps/web/app/components/workspace-mocks.ts`

- [ ] Add reusable page header, summary strip, badge, empty state, section shell, and sample data helpers.
- [ ] Keep styling aligned to the approved restrained palette and spacing rules.

### Task 2: Upgrade home and runs pages

**Files:**
- Create: `apps/web/app/components/home-page.tsx`
- Create: `apps/web/app/components/runs-page.tsx`
- Modify: `apps/web/app/page.tsx`
- Modify: `apps/web/app/runs/page.tsx`

- [ ] Replace placeholder pages with real page compositions using the new primitives.
- [ ] Expose backend-aligned fields such as readiness, reasonCode, run status, stage, stateVersion, and requestId.

### Task 3: Add run detail route and page

**Files:**
- Create: `apps/web/app/components/run-detail-page.tsx`
- Create: `apps/web/app/runs/[runId]/page.tsx`

- [ ] Add a first-pass run detail page with overview, events, logs, outputs, and spec sections.
- [ ] Make the route export-safe with static params.

### Task 4: Polish shell and supporting pages

**Files:**
- Modify: `apps/web/app/components/ssh-shell.tsx`
- Modify: `apps/web/app/components/ssh-shell-ui.tsx`
- Modify: `apps/web/app/components/settings-page.tsx`
- Modify: `apps/web/app/components/workspace-placeholder-page.tsx`
- Modify: `apps/web/app/servers/page.tsx`
- Modify: `apps/web/app/projects/page.tsx`
- Modify: `apps/web/app/results/page.tsx`

- [ ] Tune shell chrome, tab labeling, sidebar feedback, and terminal trigger toward the approved UI scheme.
- [ ] Bring non-priority pages up to the same visual system, even if they remain lightweight.

### Task 5: Verify

**Files:**
- Verify only

- [ ] Run app-level lint and build verification.
- [ ] Fix any TypeScript, lint, or static export issues before reporting completion.
