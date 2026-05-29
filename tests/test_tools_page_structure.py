from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def test_tools_page_has_focused_support_modules() -> None:
    api = (COMPONENTS / "tools-page-api.ts").read_text(encoding="utf-8")
    hook = (COMPONENTS / "use-tools-page-state.ts").read_text(encoding="utf-8")
    library = (COMPONENTS / "tools-page-library-section.tsx").read_text(encoding="utf-8")
    model = (COMPONENTS / "tools-page-model.ts").read_text(encoding="utf-8")
    editor = (COMPONENTS / "tools-page-rule-spec-editor.tsx").read_text(encoding="utf-8")
    ui = (COMPONENTS / "tools-page-ui.tsx").read_text(encoding="utf-8")
    page = (COMPONENTS / "tools-page.tsx").read_text(encoding="utf-8")

    assert "export async function fetchAddedTools" in api
    assert "export async function searchToolCapabilities" in api
    assert "export async function updateToolRuleTemplate" in api
    assert "/api/v1/tools/${encodeURIComponent(id)}/rule-template" in api
    assert "invalidateWorkflowToolCaches" in api
    assert "invalidateAsyncCachePrefix(\"workflow:\")" in api
    assert api.count("invalidateWorkflowToolCaches();") >= 3
    assert "TOOL_SEARCH_REQUEST_TIMEOUT_MS" in api
    assert "timeoutMs: TOOL_SEARCH_REQUEST_TIMEOUT_MS" in api
    assert "export function useToolsPageState" in hook
    assert "editingRuleSpecToolId" in hook
    assert "ruleSpecSavingId" in hook
    assert "saveToolRuleTemplate" in hook
    assert "export type ToolSearchItem" in model
    assert "localIndexAvailable?: boolean" in model
    assert "export type RuleSpecTemplate" in model
    assert "export type RuleSpecEnvironment" in model
    assert "export type RuleSpecLock" in model
    assert "ruleTemplate?: RuleSpecTemplate" in model
    assert "module?: RuleSpecModule" in model
    assert "moduleAssets?: Array<{ path: string; content: string }>" in model
    assert "lock?: RuleSpecLock" in model
    assert "export function uniqueDependencies" in model
    assert 'title="工具"' in page
    assert "添加工具" in page
    assert "返回工具库" in page
    assert "工具节点库" not in page
    assert "添加工具节点" not in page
    assert "返回节点库" not in page
    assert "在线搜索 Bioconda / conda-forge 工具" in page
    assert "加入工具失败" in hook
    assert "加入工具节点失败" not in hook
    assert "export function SourceBadge" in ui
    assert "export function ResultRow" in ui
    assert "export function ToolsLibrarySection" in library
    assert "ToolRuleSpecEditor" in library
    assert "补全 RuleSpec" in library
    assert "export function ToolRuleSpecEditor" in editor
    assert "保存 RuleSpec" in editor
    assert "RuleSpec JSON" in editor
    assert "export function ToolSearchResults" in ui
    assert "export function ToolPreviewPanel" in ui
    assert "RuleNodeSummary" in ui
    assert "RuleSpecContractPreview" in ui
    assert "ruleSpecEnvironmentItems" in ui
    assert "ruleSpecResourceItems" in ui
    assert "ruleSpecParamItems" in ui
    assert "运行环境" in ui
    assert "运行资源" in ui
    assert "参数 schema" in ui
    assert "outputSemanticTags" in ui
    assert '["directory", "protected", "temp"]' in ui
    assert "...port.semantics" in ui
    assert "工具库" in library
    assert "工具预览" in ui
    assert "加入工具" in ui
    assert "module:" in ui
    assert "规则节点库" not in ui
    assert "工具节点预览" not in ui
    assert "加入工具节点" not in ui
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
    assert "连接流程" not in library
    assert "添加到流程" not in library
