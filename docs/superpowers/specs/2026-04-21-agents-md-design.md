# Root AGENTS.md Design

## Goal

Recreate a root-level `AGENTS.md` for the whole repository as a short list of hard rules.

The file should be concise enough to read in under a minute. It should not become a workflow handbook.

## Scope

The new `AGENTS.md` applies to the whole `bio_ui/` repository.

## Required Rules

The final `AGENTS.md` must encode these repository-wide rules:

1. Do not require `pytest` by default.
2. Keep single files under 800 lines.
3. Reuse the current frontend component system: Tailwind + shadcn/ui.
4. Reuse existing frontend components before adding new ones.
5. Do not add backward-compatibility shims, silent fallbacks, or legacy support branches unless the user explicitly asks for them.
6. When old behavior is unsupported, fail loudly with a clear error instead of silently degrading.

## Repository Pointers

The file should briefly anchor the current structure:

- frontend: `apps/web`
- backend: `apps/api`
- runtime and remote execution: `core`
- preferred frontend reuse targets: `apps/web/components/ui` and `apps/web/app/components`

## Style

The final `AGENTS.md` should be:

- short
- direct
- repository-specific
- easy to scan

Target length:

- roughly 10 to 20 lines

## Exclusions

The final file should not:

- include long planning instructions
- describe a full implementation workflow
- require `pytest` for every task
- allow silent fallback behavior by default
- encourage duplicate frontend primitives

## Recommended Final Shape

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

## Acceptance Criteria

The resulting `AGENTS.md` is successful if it:

- exists at the repository root
- applies to the entire repository
- stays short
- does not require `pytest` by default
- enforces the 800-line limit
- requires reuse of the current Tailwind + shadcn/ui component system
- forbids silent fallback and default backward-compatibility work
