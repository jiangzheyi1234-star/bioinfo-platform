from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def test_tools_page_has_focused_support_modules() -> None:
    api = (COMPONENTS / "tools-page-api.ts").read_text(encoding="utf-8")
    hook = (COMPONENTS / "use-tools-page-state.ts").read_text(encoding="utf-8")
    model = (COMPONENTS / "tools-page-model.ts").read_text(encoding="utf-8")
    ui = (COMPONENTS / "tools-page-ui.tsx").read_text(encoding="utf-8")
    page = (COMPONENTS / "tools-page.tsx").read_text(encoding="utf-8")

    assert "export async function fetchAddedTools" in api
    assert "export async function searchToolCapabilities" in api
    assert "export function useToolsPageState" in hook
    assert "export type ToolSearchItem" in model
    assert "export function uniqueDependencies" in model
    assert "工具节点库" in page
    assert "添加工具节点" in page
    assert "返回节点库" in page
    assert "在线搜索 Bioconda / conda-forge 工具" in page
    assert "加入工具节点失败" in hook
    assert "export function SourceBadge" in ui
    assert "export function ResultRow" in ui
    assert "export function ToolsLibrarySection" in ui
    assert "export function ToolSearchResults" in ui
    assert "export function ToolPreviewPanel" in ui
    assert "RuleNodeSummary" in ui
    assert "outputSemanticTags" in ui
    assert '["directory", "protected", "temp"]' in ui
    assert "...port.semantics" in ui
    assert "规则节点库" in ui
    assert "工具节点预览" in ui
    assert "加入工具节点" in ui
    assert "targetPlatform=linux-64" in api
    assert "formatPlatformBadgeText" in ui
    assert "export function PlatformChips" in ui
    assert "支持平台" in ui
    assert "line-clamp-2" not in ui
    assert "function SourceBadge" not in page
    assert "function ResultRow" not in page
    assert "function uniqueDependencies" not in page
    assert "requestLocalApiJson" not in page
    assert "useEffect" not in page
    assert "useState" not in page
    assert "项目依赖" not in page
    assert "依赖预览" not in page
    assert "项目依赖" not in ui
    assert "依赖预览" not in ui
    assert "加入依赖" not in ui
