from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_APP_ROOT = REPO_ROOT / "apps" / "web" / "app"

EXPECTED_ROUTES = {
    "/",
    "/workflows",
    "/workflows/databases",
    "/workflows/detail",
    "/workflows/first-run",
    "/workflows/plugins",
    "/workflows/results",
    "/workflows/results/backfills",
    "/workflows/results/detail",
    "/workflows/results/lifecycle",
    "/workflows/results/triggers",
    "/workflows/tools",
}

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

    assert 'redirect("/workflows/first-run")' in source
    assert "EmptyWorkspacePage" not in source
    assert "FileSummaryWorkbench" not in source


def test_workflow_tabs_expose_only_current_workspace_routes() -> None:
    source = (WEB_APP_ROOT / "components" / "workflow-workspace-tabs.tsx").read_text(encoding="utf-8")

    assert 'href: "/workflows"' in source
    assert 'href: "/workflows/databases"' in source
    assert 'href: "/workflows/tools"' in source


def test_sidebar_exposes_plugin_center_route() -> None:
    source = (WEB_APP_ROOT / "components" / "ssh-shell-ui.tsx").read_text(encoding="utf-8")

    assert 'const pluginsActive = pathname === "/workflows/plugins" || pathname.startsWith("/workflows/plugins/")' in source
    assert '<Link href="/workflows/plugins" aria-current={pluginsActive ? "page" : undefined}>' in source
    assert "插件" in source
