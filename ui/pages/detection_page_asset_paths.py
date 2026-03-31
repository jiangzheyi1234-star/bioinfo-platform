from __future__ import annotations

from pathlib import Path


def resolve_detection_page_html(assets_dir: Path) -> Path:
    """Return the preferred detection-page html entrypoint.

    Phase 1/2 migration rule:
    - Prefer Vite build output if present
    - Fall back to legacy static page otherwise
    """

    normalized = Path(assets_dir)
    dist_index = normalized / "dist" / "index.html"
    if dist_index.exists():
        return dist_index
    return normalized / "index_galaxy.html"
