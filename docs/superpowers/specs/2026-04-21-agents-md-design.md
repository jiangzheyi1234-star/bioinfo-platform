# Root AGENTS.md Design

## Goal

Recreate a root-level `AGENTS.md` for the whole repository with a minimal, durable rule set.

This document is intentionally narrow. It should define the highest-signal repository rules without turning into a workflow manual.

## Scope

The new `AGENTS.md` applies to the entire repository at `bio_ui/`.

It should guide future agents working in:

- `apps/web`
- `apps/api`
- `core`
- supporting docs and tests

## Constraints

The document must encode these explicit user requirements:

1. `pytest` is not required by default.
2. A single file should not exceed 800 lines.
3. Frontend work should reuse the current Tailwind + shadcn/ui component system.

## Proposed Content

The root `AGENTS.md` should stay short and contain four sections.

### 1. Repository Direction

State the current architecture at a high level:

- desktop-first pathogen analysis workbench
- frontend in `apps/web`
- backend in `apps/api`
- runtime and remote execution logic in `core`

This section should discourage cross-layer changes unless necessary.

### 2. Validation Rules

State that `pytest` is not a default completion requirement.

Preferred verification should be the checks most relevant to the actual change, such as:

- targeted build commands
- type checks
- frontend lint
- focused manual or API validation

If the user explicitly requests `pytest`, it becomes required for that task.

### 3. File Size Rule

State a hard preference that a single file should remain under 800 lines.

When an edit would push a file past the limit, the preferred action is to split responsibilities into smaller modules instead of continuing to grow the file.

This rule should apply to both new files and modified files.

### 4. Frontend Reuse Rule

State that frontend changes should reuse the existing Tailwind + shadcn/ui stack.

The preferred reuse targets are:

- `apps/web/components/ui`
- `apps/web/app/components`

Agents should avoid creating duplicate primitives such as:

- buttons
- inputs
- dialogs
- layout shells

New components are acceptable only when the existing component inventory cannot support the change cleanly.

## Non-Goals

The root `AGENTS.md` should not:

- duplicate long process instructions
- define a full planning workflow
- require global refactors
- require `pytest` for every change
- introduce a second frontend component system

## Recommended Shape

The final file should be concise enough to scan quickly during task startup.

Recommended length:

- roughly 20 to 40 lines

Recommended tone:

- direct
- repository-specific
- low-ambiguity

## Example Structure

```md
# Repository Instructions

## Architecture
- ...

## Validation
- ...

## File Size
- ...

## Frontend
- ...
```

## Risks

### Risk 1: Too much policy

If the file grows into a full workflow handbook, agents will ignore or inconsistently apply it.

Mitigation:

Keep only the repository rules that are stable and repeatedly useful.

### Risk 2: Frontend rule too vague

If the component reuse rule does not name the current reuse targets, future agents may still create parallel component trees.

Mitigation:

Name the existing component locations explicitly.

### Risk 3: Validation rule misread as "no testing"

Saying "`pytest` is not required" could be misread as "verification is optional."

Mitigation:

State that verification is still required, but should be relevant to the change instead of defaulting to `pytest`.

## Acceptance Criteria

The resulting `AGENTS.md` is successful if it:

- exists at the repository root
- applies to the whole repository
- does not require `pytest` by default
- enforces the 800-line file limit
- tells agents to reuse the current Tailwind + shadcn/ui component system
- remains short and easy to scan
