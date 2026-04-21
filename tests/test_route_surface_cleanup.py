from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_APP_ROOT = REPO_ROOT / "apps" / "web" / "app"


def test_root_route_remains_a_servers_redirect() -> None:
    page_path = WEB_APP_ROOT / "page.tsx"
    content = page_path.read_text(encoding="utf-8")

    assert 'redirect("/servers")' in content


def test_redirect_only_route_directories_are_absent() -> None:
    removed_route_dirs = [
        WEB_APP_ROOT / "connect",
        WEB_APP_ROOT / "projects",
        WEB_APP_ROOT / "runs",
        WEB_APP_ROOT / "results",
    ]

    for route_dir in removed_route_dirs:
        assert not route_dir.exists(), f"legacy redirect-only route directory should stay removed: {route_dir}"


def test_canonical_workspace_routes_remain_available() -> None:
    expected_pages = [
        WEB_APP_ROOT / "page.tsx",
        WEB_APP_ROOT / "servers" / "page.tsx",
        WEB_APP_ROOT / "servers" / "[serverId]" / "page.tsx",
        WEB_APP_ROOT / "settings" / "page.tsx",
    ]

    for page_path in expected_pages:
        assert page_path.exists(), f"expected canonical route file is missing: {page_path}"
