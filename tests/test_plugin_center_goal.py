from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"
PLUGIN_ROUTE = ROOT / "apps" / "web" / "app" / "workflows" / "plugins" / "page.tsx"
ROADMAP = ROOT / "docs" / "roadmaps" / "plugin-extension-center-goal.md"


def test_plugin_center_goal_document_defines_boundaries_and_phases() -> None:
    source = ROADMAP.read_text(encoding="utf-8")

    assert "SSH is the connection channel, not the plugin" in source
    assert "Remote provisioning job" in source
    assert "tool preparation and remote executor provisioning into one backend domain model" in source
    assert "### Phase 1: Navigation And Goal Surface" in source
    assert "### Phase 3: Local Provisioning Job Contract" in source
    assert "### Phase 4: First-Class Server Profiles" in source
    assert "The optional thin CLI should be a management shell around the service" in source


def test_plugin_center_route_surfaces_phase_one_cards() -> None:
    route_source = PLUGIN_ROUTE.read_text(encoding="utf-8")
    page_source = (COMPONENTS / "plugin-center-page.tsx").read_text(encoding="utf-8")
    sidebar_source = (COMPONENTS / "ssh-shell-ui.tsx").read_text(encoding="utf-8")

    assert "PluginCenterPage" in route_source
    assert 'data-testid="plugin-center-page"' in page_source
    assert 'testId="plugin-center-remote-executor-card"' in page_source
    assert 'testId="plugin-center-tool-plugins-card"' in page_source
    assert 'testId="plugin-center-runtime-components-card"' in page_source
    assert 'testId="plugin-center-installation-tasks-card"' in page_source
    assert 'data-testid="plugin-center-remote-executor-stage-list"' in page_source
    assert "useWorkflowRunnerRepairState" in page_source
    assert "useToolPrepareTasks" in page_source
    assert "RunnerRepairPanel" in page_source
    assert 'Link href="/workflows/tools"' in page_source
    assert 'Link href="/workflows/plugins"' in sidebar_source
    assert "pluginsActive" in sidebar_source
