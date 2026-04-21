# Root AGENTS.md Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recreate a short root-level `AGENTS.md` that applies to the whole repository and encodes the approved hard rules.

**Architecture:** Replace the missing root `AGENTS.md` with a concise markdown file at the repository root. Keep the file intentionally short, repository-scoped, and limited to the approved constraints: no default `pytest` requirement, 800-line file limit, frontend reuse through the existing Tailwind + shadcn/ui component system, and fail-loudly semantics instead of backward-compatibility layers or silent fallback behavior.

**Tech Stack:** Markdown, git

---

### Task 1: Recreate the root AGENTS.md file

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Replace the missing root file with the approved content**

Use this exact file content:

```md
# Repository Instructions

- Frontend lives in `apps/web`; backend in `apps/api`; runtime logic in `core`.
- Do not require `pytest` by default. Run only the verification relevant to the change unless the user explicitly asks for `pytest`.
- Keep single files under 800 lines. Split responsibilities instead of growing past the limit.
- Frontend work must reuse the existing Tailwind + shadcn/ui system.
- Reuse `apps/web/components/ui` and `apps/web/app/components` before adding new components.
- Do not add backward-compatibility layers, silent fallbacks, or legacy branches unless explicitly requested.
- When older behavior is unsupported, fail loudly and clearly instead of degrading silently.
```

- [ ] **Step 2: Verify the file content matches the approved design**

Run:

```bash
sed -n '1,80p' AGENTS.md
```

Expected:

```text
Output shows the seven approved repository rules and no extra workflow sections.
```

- [ ] **Step 3: Verify the file remains concise**

Run:

```bash
wc -l AGENTS.md
```

Expected:

```text
The line count is low and stays within the intended short format.
```

- [ ] **Step 4: Verify the working tree change is isolated**

Run:

```bash
git diff -- AGENTS.md
```

Expected:

```text
The diff shows only the recreated root AGENTS.md content and no unrelated edits in this file.
```

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md
git commit -m "Restore concise root AGENTS.md rules"
```

### Task 2: Final review against the approved spec

**Files:**
- Modify: `AGENTS.md`
- Reference: `docs/superpowers/specs/2026-04-21-agents-md-design.md`

- [ ] **Step 1: Cross-check each approved rule against the new root file**

Review this checklist:

```md
- `pytest` is not required by default.
- Single files should stay under 800 lines.
- Frontend work reuses Tailwind + shadcn/ui.
- Existing frontend components are reused first.
- Backward-compatibility shims and silent fallbacks are disallowed by default.
- Unsupported old behavior should fail loudly.
```

- [ ] **Step 2: Confirm the final file did not drift beyond the minimal scope**

Run:

```bash
sed -n '1,80p' AGENTS.md
```

Expected:

```text
The file remains a short rules list, not a process handbook.
```

- [ ] **Step 3: Commit any last wording adjustment if needed**

```bash
git add AGENTS.md
git commit -m "Polish root AGENTS.md wording" || true
```
