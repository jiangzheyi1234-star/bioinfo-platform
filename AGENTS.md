# Repository Instructions

- Frontend lives in `apps/web`; backend in `apps/api`; runtime logic in `core`.
- Do not require `pytest` by default. Run only the verification relevant to the change unless the user explicitly asks for `pytest`.
- Keep single files under 800 lines. Split responsibilities instead of growing past the limit.
- Frontend work must reuse the existing Tailwind + shadcn/ui system.
- Reuse `apps/web/components/ui` and `apps/web/app/components` before adding new components.
- Do not depend on WSL-based builds; when working from Windows, consume prebuilt artifacts instead of requiring WSL to produce Linux deployment outputs.
- Do not add backward-compatibility layers, silent fallbacks, or legacy branches unless explicitly requested.
- When older behavior is unsupported, fail loudly and clearly instead of degrading silently.
