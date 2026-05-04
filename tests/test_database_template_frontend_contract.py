from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"

CONTRACT_FILES = {
    "page": COMPONENTS / "databases-page.tsx",
    "add_panel": COMPONENTS / "databases-add-panel.tsx",
    "item_list": COMPONENTS / "databases-item-list.tsx",
    "state": COMPONENTS / "use-databases-page-state.ts",
    "api": COMPONENTS / "database-page-api.ts",
    "model": COMPONENTS / "database-page-model.ts",
    "ui": COMPONENTS / "database-page-ui.tsx",
    "path_utils": COMPONENTS / "database-path-utils.ts",
    "details": COMPONENTS / "database-validation-details-dialog.tsx",
}


def _source(*names: str) -> str:
    selected = names or tuple(CONTRACT_FILES)
    return "\n".join(CONTRACT_FILES[name].read_text(encoding="utf-8") for name in selected)


def _assert_contains(source: str, *tokens: str) -> None:
    for token in tokens:
        assert token in source


def _assert_not_contains(source: str, *tokens: str) -> None:
    for token in tokens:
        assert token not in source


def test_databases_page_does_not_ship_legacy_template_fallbacks() -> None:
    source = _source()

    _assert_not_contains(
        source,
        "FALLBACK_DATABASE_TEMPLATES",
        "setTemplates(FALLBACK",
        "ensureDatabaseAvailable",
    )


def test_template_model_keeps_path_kind_and_stable_template_contract() -> None:
    source = _source("model")

    _assert_contains(
        source,
        'type PathKind = "directory" | "file" | "prefix" | "primary_with_sidecars" | "composite"',
        "fields?: Record<string, DatabaseTemplateField>",
        'supportLevel?: "stable"',
        "复合数据库需要填写多个路径字段。",
        "runtimeValue",
        "templateCheckItemList(",
        "stableComplexityCopy(",
        "runtimeHint(",
    )
    _assert_not_contains(source, "复合数据库暂未支持，请先使用单路径模板。")


def test_add_form_supports_composite_fields_and_submits_multi_database_metadata() -> None:
    source = _source("add_panel", "state", "api", "path_utils")

    _assert_contains(
        source,
        "compositeFields",
        "compositeFieldEntries(",
        "updateCompositeField(",
        "selectBrowserPathForCompositeField(",
        "metadataInput",
        'kind: "multi"',
        "fields: compositeInputFields",
        "compositeReady",
        "selectedEntryPath",
    )


def test_remote_browser_keeps_navigation_selection_and_pagination_contracts() -> None:
    source = _source("page", "add_panel", "state", "api", "model", "path_utils")

    _assert_contains(
        source,
        'type PathSelectionMode = "none" | "browser" | "manual"',
        "selectionMode",
        "selectBrowserPath(",
        "editManualPath(",
        "loadRemotePath(item.path)",
        "onClick={() => selectBrowserPath(browserPath)}",
        "onClick={() => selectBrowserPath(item.path)}",
        "REMOTE_BROWSER_PAGE_SIZE = 500",
        "offset=${offset}",
        "加载更多",
        "已分批加载",
        "handleBrowserScroll",
        "onScroll={handleBrowserScroll}",
        "candidateDetailFromError(",
        "请选择数据库入口",
        "selectedEntryPath",
        "选择此索引",
        "选择 FASTA 主文件",
        "索引文件不能作为 FASTA 主文件",
        r"\.(amb|ann|bwt|pac|sa)$",
    )
    _assert_not_contains(
        source,
        "browserSelectionPath",
        "detectedPrefixCandidates(",
        "detectedFileCandidates(",
        "detectedPrimaryCandidates(",
        "detectedTargetCandidates(",
        "selectDetectedTarget(",
        "切换并选择",
    )


def test_validation_status_messages_and_details_dialog_remain_visible() -> None:
    source = _source("item_list", "details")

    _assert_contains(
        source,
        "item.message",
        "查看校验详情",
        "DatabaseValidationDetailsDialog",
        "工具探测：",
        "stdout",
        "stderr",
        "实际执行命令",
        "返回码",
    )


def test_resolved_tool_path_is_explained_when_it_differs_from_selected_path() -> None:
    source = _source("item_list", "path_utils", "details")

    _assert_contains(
        source,
        "resolvedPath",
        "databaseToolPath",
        "实际工具路径",
        'resolved?.kind === "prefix"',
        'resolved?.kind === "file"',
        'resolved?.kind === "directory"',
        'resolved?.kind === "primary_with_sidecars"',
        "resolved.firstIndexPrefix || resolved.firstMatch || resolved.path",
        "resolved?.firstIndexPrefix || resolved?.firstMatch || resolved?.path",
        "availableReadLengths",
        "路径如何传给工具",
    )


def test_declared_database_is_not_treated_as_validated() -> None:
    source = _source("item_list", "state", "api", "model")

    _assert_contains(
        source,
        'item.status === "declared"',
        "未校验",
        'if (database.status !== "available")',
        'throw new Error(database.message || "数据库添加接口未返回可用状态。")',
    )


def test_database_registration_language_and_grouped_template_types_stay_user_facing() -> None:
    source = _source("add_panel", "model")

    _assert_contains(
        source,
        "数据库类型",
        "分类学数据库",
        "比对索引",
        "注释数据库",
        'category: "taxonomy"',
        'category: "alignment"',
        'category: "annotation"',
        "function templateCategory(",
        "templateCategory(template) === group.category",
        "{saving ? \"校验中\" : \"校验并保存\"}",
    )
    _assert_not_contains(source, "选择模板", "加入中")


def test_repeated_check_items_use_stable_duplicate_safe_keys() -> None:
    source = _source("add_panel")

    _assert_contains(source, ".map((item, index) =>", "key={`${item}-${index}`}")
    _assert_not_contains(source, "key={item}")
