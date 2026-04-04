# History Table Linear + Handcrafted Prompt

## Goal
Implement a production-ready redesign for the Detection "任务历史" table with:
1. Linear minimal visual language (clean light mode)
2. Subtle handcrafted paper-like texture
3. Stripe/Freshsales-like smooth expand card interaction
4. Strong typography system (font family, scale, numeric alignment)

## Scope
- Only Detection history module frontend assets:
  - `ui/pages/detection_page_assets/index_galaxy.html`
  - `ui/pages/detection_page_assets/styles_galaxy.css`
  - `ui/pages/detection_page_assets/render/history_panel.js`
  - `ui/pages/detection_page_assets/render/history_status.js`

## Out Of Scope
- Backend API/schema changes.
- Database, tool-form, integrated result-page visual overhaul.
- Any runtime fallback for removed styling contracts.

## Success Criteria
1. History table stays minimal and readable at first glance.
2. Handcrafted texture is subtle (visible only on close look).
3. Expanded details open smoothly in ~180ms as a modern rounded card.
4. Typography hierarchy is explicit and consistent.
5. Refresh/delete icons are linear SVG, no emoji/unicode icon dependency.

## Hard Constraints
- Fail loudly; no silent fallback.
- No preserving deleted-field compatibility references.
- `pytest` is user-owned in this environment.
- Keep changes scoped and reversible.

## Reference
- OpenAI blog: Run long-horizon tasks with Codex
  https://developers.openai.com/blog/run-long-horizon-tasks-with-codex
