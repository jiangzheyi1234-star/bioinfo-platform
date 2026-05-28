# Generated Workflow Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a generated workflow builder that submits explicit Phase 6 DAG contracts instead of implicit selected-tool order.

**Architecture:** Add a generated-workflow model for draft state, validation, and runSpec construction; add a small hook to manage draft edits; add a focused builder UI and connect it to the existing workflow run page. Keep backend validation authoritative while surfacing clear frontend errors before submit.

**Tech Stack:** Next.js 15, React 19, TypeScript, Tailwind, shadcn/ui, lucide-react.

---

### Task 1: Contract Model

**Files:**
- Create: `apps/web/app/components/generated-workflow-model.ts`
- Modify: `apps/web/app/components/workflows-page-model.ts`
- Modify: `tests/test_workflows_page_structure.py`

- [ ] Write a failing structure test that requires a generated workflow model, explicit input bindings, exposed outputs, and no legacy generated database field.
- [ ] Run the focused structure test from a WSL Codex CLI only; in this Windows session do not run pytest.
- [ ] Implement `GeneratedWorkflowDraft`, `GeneratedWorkflowStepDraft`, `GeneratedWorkflowInputBinding`, validation helpers, and `buildGeneratedWorkflowRunSpec`.
- [ ] Keep existing normal pipeline runSpec behavior unchanged.

### Task 2: Builder State Hook

**Files:**
- Create: `apps/web/app/components/use-generated-workflow-builder.ts`
- Modify: `apps/web/app/components/use-workflows-page-state.ts`

- [ ] Add reducer actions for adding/removing steps, selecting tools, setting input bindings, exposing outputs, and clearing invalid references.
- [ ] Derive validation, selected tools, resource bindings, and `canSubmit`.
- [ ] Connect generated run submission to the explicit draft runSpec.

### Task 3: Builder UI

**Files:**
- Create: `apps/web/app/components/generated-workflow-builder.tsx`
- Modify: `apps/web/app/components/workflows-page-ui.tsx`
- Modify: `apps/web/app/components/workflow-detail-page.tsx`

- [ ] Replace generated-tool checkbox groups with the dedicated builder UI.
- [ ] Use shadcn `Button`, `Select`, `Input`, `Alert`, and existing Tailwind density.
- [ ] Surface missing input/output/cycle validation messages near the builder.
- [ ] Keep each hand-written source file below 800 lines.

### Task 4: Verification

**Files:**
- Modify: `tests/test_workflows_page_structure.py`

- [ ] Run `npm run build` in `apps/web`.
- [ ] Ask the user to run the focused Python tests from WSL Codex CLI because Windows Codex must not run pytest.
- [ ] Inspect `git diff --stat` and source file line counts.
