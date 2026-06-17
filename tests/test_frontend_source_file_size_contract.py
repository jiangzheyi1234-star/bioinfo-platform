from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = REPOSITORY_ROOT / "apps" / "web"
MAX_HAND_WRITTEN_FRONTEND_SOURCE_LINES = 800

LEGACY_OVERSIZED_FRONTEND_FILES = {
    "apps/web/app/components/tools-page-model.ts": 933,
    "apps/web/app/components/tools-page-ui.tsx": 897,
}


def _frontend_source_files() -> list[Path]:
    return [
        path
        for suffix in ("*.ts", "*.tsx")
        for path in FRONTEND_ROOT.rglob(suffix)
        if "node_modules" not in path.parts
        and ".next" not in path.parts
        and path.name != "next-env.d.ts"
    ]


def test_frontend_source_files_stay_under_line_limit_or_known_ceiling() -> None:
    new_oversized: dict[str, int] = {}
    legacy_regressions: dict[str, dict[str, int]] = {}

    for path in _frontend_source_files():
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count <= MAX_HAND_WRITTEN_FRONTEND_SOURCE_LINES:
            continue
        legacy_ceiling = LEGACY_OVERSIZED_FRONTEND_FILES.get(relative)
        if legacy_ceiling is None:
            new_oversized[relative] = line_count
        elif line_count > legacy_ceiling:
            legacy_regressions[relative] = {"current": line_count, "ceiling": legacy_ceiling}

    assert new_oversized == {}
    assert legacy_regressions == {}
