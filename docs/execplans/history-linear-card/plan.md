# History Table Linear + Handcrafted Plan

## Execution Rules
1. This plan is the sole execution source of truth for this task.
2. Only one milestone can be in progress at a time.
3. Every milestone must pass its verification before moving on.
4. If verification fails: repair first, then continue.

## Milestones

### M0 Baseline Freeze
Status: pending

Outputs:
- Freeze current history render/expand/icon structure.
- Record typography and layout baseline.

Acceptance:
- Baseline entries added to `documentation.md`.

Verification:
- `rg -n "history-page|task-row|task-details|history-refresh-btn|btn-delete|font-family" ui/pages/detection_page_assets -S`

---

### M1 Typography System for History
Status: pending

Outputs:
- History-local typography tokens and font stack (`Geist + Noto Sans SC` fallback chain).
- Numeric columns use tabular numerals.

Acceptance:
- Header/body/meta text hierarchy is explicit in CSS.

Verification:
- `rg -n "history-typo|font-variant-numeric|history-page" ui/pages/detection_page_assets/styles_galaxy.css -S`

---

### M2 Linear Surface + Subtle Paper Texture
Status: pending

Outputs:
- Refined table card/surface with thin linear separators.
- Subtle texture overlay on history card/header.

Acceptance:
- Texture layer exists and remains low-opacity.

Verification:
- `rg -n "history-texture|history-surface|task-list-header" ui/pages/detection_page_assets/styles_galaxy.css -S`

---

### M3 Expand Details as Smooth Modern Card
Status: pending

Outputs:
- Replace display none/block details behavior with smooth 180ms expand/collapse.
- Single-card details layout for error/JSON/remote status.

Acceptance:
- Expand region is animation-capable and styled as rounded shadowed card.

Verification:
- `rg -n "task-details|task-details-inner|task-details-card|expanded|180ms" ui/pages/detection_page_assets/styles_galaxy.css ui/pages/detection_page_assets/render/history_panel.js -S`

---

### M4 Replace Refresh/Delete with Linear SVG Icons
Status: pending

Outputs:
- Refresh button icon updated to inline SVG.
- Delete action icon updated to inline SVG in row actions.

Acceptance:
- No unicode-symbol icon used for refresh/delete.

Verification:
- `rg -n "svg|history-refresh-icon|btn-delete|⌫|↻" ui/pages/detection_page_assets/index_galaxy.html ui/pages/detection_page_assets/render/history_panel.js -S`

---

### M5 Integration Sweep and Documentation
Status: pending

Outputs:
- Ensure history remote status block still renders in new details card.
- Update execution documentation with verification outputs and residual risks.

Acceptance:
- Final status board shows M0-M5 completed.

Verification:
- `rg -n "remote-status-block|task-details|history" ui/pages/detection_page_assets/render/history_status.js ui/pages/detection_page_assets/render/history_panel.js ui/pages/detection_page_assets/styles_galaxy.css -S`

## Dependency Order
M0 -> M1 -> M2 -> M3 -> M4 -> M5
