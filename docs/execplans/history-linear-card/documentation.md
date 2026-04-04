# History Table Linear + Handcrafted Documentation

## Meta
- Task: Detection history table visual/interaction redesign
- Start date: 2026-04-04
- Owner: Codex + User
- Source plan: `docs/execplans/history-linear-card/plan.md`

## Status Board

| Milestone | Status | Last Update | Notes |
|---|---|---|---|
| M0 Baseline Freeze | completed | 2026-04-04 | Existing history render/expand/icon baseline frozen via grep snapshot |
| M1 Typography System | completed | 2026-04-04 | Added history-local typography tokens and tabular numerals |
| M2 Surface + Texture | completed | 2026-04-04 | Added linear surface + subtle paper texture overlay |
| M3 Expand Card Animation | completed | 2026-04-04 | Replaced abrupt details toggle with smooth 180ms card expand |
| M4 Linear SVG Icons | completed | 2026-04-04 | Refresh/delete action icons migrated to inline SVG |
| M5 Integration Sweep | completed | 2026-04-04 | Remote status insertion preserved in new details card body |

## Work Log

### M0 Baseline Freeze
- Status: completed
- Date: 2026-04-04
- Scope:
  - Freeze current history styles and interaction entry points before refactor.
- Edits:
  - file: none (observation milestone)
  - reason: baseline inventory only.
- Verification:
  - command: `rg -n "history-page|task-row|task-details|history-refresh-btn|btn-delete|font-family" ui/pages/detection_page_assets -S`
  - result: confirmed old inline icon text (`↻`, `⌫`) and old details block path existed.
- Failures & Repairs:
  - issue: none
  - fix: none
- Residual Risk:
  - Large existing `styles_galaxy.css` history block remains and may conflict if selector specificity regresses.
- Next Step:
  - Extract new history-specific style layer and apply scoped overrides.

### M1 Typography System
- Status: completed
- Date: 2026-04-04
- Scope:
  - Introduce history-local font stack, text scale, and numeric alignment rules.
- Edits:
  - file: `ui/pages/detection_page_assets/history_linear_theme.css`
  - reason: avoid adding more complexity to `styles_galaxy.css` (>600 lines) and centralize history typography rules.
- Verification:
  - command: `rg -n "history-typo|font-variant-numeric|history-page" ui/pages/detection_page_assets/history_linear_theme.css ui/pages/detection_page_assets/styles_galaxy.css -S`
  - result: history typography tokens and tabular numerics found in new history theme.
- Failures & Repairs:
  - issue: none
  - fix: none
- Residual Risk:
  - `Geist` depends on host availability; fallback chain still guarantees readable sans-serif.
- Next Step:
  - Land surface and texture layer with conservative opacity.

### M2 Surface + Texture
- Status: completed
- Date: 2026-04-04
- Scope:
  - Apply linear card/surface polish and subtle paper-like texture overlays.
- Edits:
  - file: `ui/pages/detection_page_assets/history_linear_theme.css`
  - reason: add low-opacity texture tokens and structured surface hierarchy.
- Verification:
  - command: `rg -n "history-texture|history-surface|task-list-header" ui/pages/detection_page_assets/history_linear_theme.css ui/pages/detection_page_assets/styles_galaxy.css -S`
  - result: texture/surface tokens and header layering present.
- Failures & Repairs:
  - issue: none
  - fix: none
- Residual Risk:
  - Texture visibility may vary by display gamma.
- Next Step:
  - Refactor detail panel structure and animation.

### M3 Expand Card Animation
- Status: completed
- Date: 2026-04-04
- Scope:
  - Convert details panel to smooth expandable modern card behavior.
- Edits:
  - file: `ui/pages/detection_page_assets/render/history_panel.js`
  - reason: replace inline click string toggling with explicit event handlers and accessible state updates.
  - file: `ui/pages/detection_page_assets/history_linear_theme.css`
  - reason: implement 180ms grid/opacity/transform transitions and new detail card skin.
  - file: `ui/pages/detection_page_assets/render/history_status.js`
  - reason: adapt remote-status insertion target to `.task-details-card-body`.
- Verification:
  - command: `rg -n "task-details|task-details-inner|task-details-card|expanded|180ms" ui/pages/detection_page_assets/history_linear_theme.css ui/pages/detection_page_assets/render/history_panel.js -S`
  - result: new card structure and 180ms transitions confirmed.
- Failures & Repairs:
  - issue: none
  - fix: none
- Residual Risk:
  - Runtime animation smoothness still requires user-side visual confirmation.
- Next Step:
  - Complete icon migration to SVG.

### M4 Linear SVG Icons
- Status: completed
- Date: 2026-04-04
- Scope:
  - Replace refresh and delete text icons with linear SVG.
- Edits:
  - file: `ui/pages/detection_page_assets/index_galaxy.html`
  - reason: refresh button now uses inline SVG icon.
  - file: `ui/pages/detection_page_assets/render/history_panel.js`
  - reason: delete action icon now uses inline SVG helper.
- Verification:
  - command: `rg -n "svg|history-refresh-icon|btn-delete|⌫|↻" ui/pages/detection_page_assets/index_galaxy.html ui/pages/detection_page_assets/render/history_panel.js -S`
  - result: `svg` and new icon selectors present; old unicode icon characters removed.
- Failures & Repairs:
  - issue: none
  - fix: none
- Residual Risk:
  - None observed in static checks.
- Next Step:
  - Perform integration sweep and syntax checks.

### M5 Integration Sweep
- Status: completed
- Date: 2026-04-04
- Scope:
  - Ensure remote status and details rendering remain consistent with new card structure.
- Edits:
  - file: `ui/pages/detection_page_assets/render/history_status.js`
  - reason: keep `remote-status-block` insertion/removal behavior with updated DOM.
  - file: `ui/pages/detection_page_assets/index_galaxy.html`
  - reason: include `history_linear_theme.css` after existing theme files.
- Verification:
  - command: `rg -n "remote-status-block|task-details|history" ui/pages/detection_page_assets/render/history_status.js ui/pages/detection_page_assets/render/history_panel.js ui/pages/detection_page_assets/history_linear_theme.css -S`
  - result: insertion/removal hooks and detail-card classes aligned.
  - command: `node --check ui/pages/detection_page_assets/render/history_panel.js`
  - result: passed.
  - command: `node --check ui/pages/detection_page_assets/render/history_status.js`
  - result: passed.
- Failures & Repairs:
  - issue: none
  - fix: none
- Residual Risk:
  - Final look-and-feel should be validated in real UI runtime by user.
- Next Step:
  - Hand off for visual acceptance.
