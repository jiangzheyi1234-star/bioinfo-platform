from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_APP_ROOT = REPO_ROOT / "apps" / "web" / "app"

EXPECTED_ROUTES = {
    "/",
    "/settings",
    "/workflows",
    "/workflows/databases",
    "/workflows/detail",
    "/workflows/results",
    "/workflows/results/detail",
    "/workflows/tools",
}

LEGACY_ROUTE_PAGES = [
    WEB_APP_ROOT / "servers" / "page.tsx",
    WEB_APP_ROOT / "servers" / "[serverId]" / "page.tsx",
    WEB_APP_ROOT / "connect" / "page.tsx",
    WEB_APP_ROOT / "projects" / "page.tsx",
    WEB_APP_ROOT / "runs" / "page.tsx",
    WEB_APP_ROOT / "results" / "page.tsx",
    WEB_APP_ROOT / "workflows" / "resources" / "page.tsx",
]


def _route_for_page(page_path: Path) -> str:
    route_dir = page_path.parent.relative_to(WEB_APP_ROOT)
    if route_dir == Path("."):
        return "/"
    return "/" + route_dir.as_posix()


def test_frontend_route_surface_matches_current_workspace_routes() -> None:
    actual_routes = {_route_for_page(path) for path in WEB_APP_ROOT.rglob("page.tsx")}

    assert actual_routes == EXPECTED_ROUTES


def test_root_route_redirects_to_workflows() -> None:
    source = (WEB_APP_ROOT / "page.tsx").read_text(encoding="utf-8")

    assert 'redirect("/workflows")' in source
    assert "EmptyWorkspacePage" not in source
    assert 'redirect("/servers")' not in source
    assert "FileSummaryWorkbench" not in source


def test_legacy_route_pages_are_not_shipped() -> None:
    for page_path in LEGACY_ROUTE_PAGES:
        assert not page_path.exists(), f"legacy route page should stay removed: {page_path}"


def test_workflow_tabs_expose_only_current_workspace_routes() -> None:
    source = (WEB_APP_ROOT / "components" / "workflow-workspace-tabs.tsx").read_text(encoding="utf-8")

    assert 'href: "/workflows"' in source
    assert 'href: "/workflows/databases"' in source
    assert 'href: "/workflows/tools"' in source
    assert "/workflows/resources" not in source
    assert "资源配置" not in source
