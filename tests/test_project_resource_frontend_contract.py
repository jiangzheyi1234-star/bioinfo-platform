from __future__ import annotations

from pathlib import Path


def test_workflow_workspace_does_not_expose_project_resource_config_tab() -> None:
    tabs = Path("apps/web/app/components/workflow-workspace-tabs.tsx").read_text(encoding="utf-8")

    assert "/workflows/resources" not in tabs
    assert "资源配置" not in tabs


def test_project_resource_config_page_route_is_not_shipped() -> None:
    assert not Path("apps/web/app/workflows/resources/page.tsx").exists()
    assert not Path("apps/web/app/components/project-resource-config-page.tsx").exists()
