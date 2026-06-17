from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"

CONTRACT_FILES = {
    "page": COMPONENTS / "databases-page.tsx",
    "pack_section": COMPONENTS / "database-pack-section.tsx",
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


def _assert_in_order(source: str, *snippets: str) -> None:
    index = -1
    for snippet in snippets:
        next_index = source.find(snippet, index + 1)
        assert next_index != -1
        index = next_index


def _path_utils_behavior_script() -> str:
    source = _source("path_utils")
    start = source.index("function normalizeCompositePath")
    end = source.index("function isBwaIndexFile")
    implementation = source[start:end]
    implementation = re.sub(
        r"export function compositeFallbackPath\(values: Record<string, string>\)",
        "function compositeFallbackPath(values)",
        implementation,
    )
    implementation = re.sub(
        r"function (normalizeCompositePath|compositePathRoot)\(value: string\)",
        r"function \1(value)",
        implementation,
    )
    implementation = implementation.replace(
        "function compositePathSegments(value: string, root: string)",
        "function compositePathSegments(value, root)",
    )
    implementation = implementation.replace(
        "function commonCompositePath(values: string[])",
        "function commonCompositePath(values)",
    )
    return f"""
{implementation}

const cases = [
  {{
    name: "windows same directory keeps drive-qualified parent",
    values: {{ fasta: "C:/foo/ref.fa", index: "C:/foo/ref.idx" }},
    expected: "C:/foo",
  }},
  {{
    name: "windows siblings preserve drive root",
    values: {{ fasta: "C:/foo/ref.fa", index: "C:/bar/ref.idx" }},
    expected: "C:/",
  }},
  {{
    name: "windows cross-drive paths do not degrade to a bare drive",
    values: {{ fasta: "C:/foo/ref.fa", index: "D:/foo/ref.idx" }},
    expected: ".",
  }},
  {{
    name: "unix same directory keeps absolute parent",
    values: {{ fasta: "/foo/ref.fa", index: "/foo/ref.idx" }},
    expected: "/foo",
  }},
  {{
    name: "unix siblings preserve filesystem root",
    values: {{ fasta: "/foo/ref.fa", index: "/bar/ref.idx" }},
    expected: "/",
  }},
  {{
    name: "relative siblings stay relative",
    values: {{ fasta: "foo/ref.fa", index: "bar/ref.idx" }},
    expected: ".",
  }},
  {{
    name: "windows backslashes normalize before common path detection",
    values: {{ fasta: "C:\\\\foo\\\\ref.fa", index: "C:\\\\foo\\\\ref.idx" }},
    expected: "C:/foo",
  }},
];

const failures = cases
  .map((current) => ({{ ...current, actual: compositeFallbackPath(current.values) }}))
  .filter((current) => current.actual !== current.expected);

if (failures.length > 0) {{
  console.error(JSON.stringify(failures, null, 2));
  process.exit(1);
}}
"""


def test_template_model_keeps_path_kind_and_stable_template_contract() -> None:
    source = _source("model")

    _assert_contains(
        source,
        'type PathKind = "directory" | "file" | "prefix" | "primary_with_sidecars" | "composite"',
        'type DatabaseLayer = "production_full" | "validation_fixture" | "user_manual" | "downloadable_pack" | "unspecified"',
        "databaseLayer?: DatabaseLayer",
        "productionEligible?: boolean",
        "fixtureScope?: string",
        "supportedLayers?: DatabaseLayer[]",
        "fields?: Record<string, DatabaseTemplateField>",
        "type DatabasePack = {",
        'lifecycleContractVersion: "database-pack-lifecycle-v1"',
        'installMode: "manual_external"',
        "operatorActionRequired: true",
        "noAutomaticExecution: true",
        'databaseLayer: "downloadable_pack"',
        "archiveSizeBytes: number",
        "manualInstall: DatabasePackManualInstall",
        "registrationHandoff: DatabasePackRegistrationHandoff",
        "evidencePolicy: DatabasePackEvidencePolicy",
        "type DatabasePacksResponse",
        'supportLevel?: "stable"',
        "复合数据库需要填写多个路径字段。",
        "runtimeValue",
        "templateCheckItemList(",
        "stableComplexityCopy(",
        "runtimeHint(",
    )
    _assert_not_contains(source, "复合数据库暂未支持，请先使用单路径模板。")


def test_downloadable_pack_frontend_contract_stays_read_only() -> None:
    model_source = _source("model")
    api_source = _source("api")
    page_source = _source("page")
    state_source = _source("state")
    pack_section_source = _source("pack_section")
    create_input = api_source.split("export type CreateDatabaseInput", 1)[1].split(
        "export type UpdateDatabaseInput",
        1,
    )[0]

    _assert_contains(
        model_source,
        "type DatabasePackManualInstall = {",
        "type DatabasePackRegistrationHandoff = {",
        "type DatabasePackEvidencePolicy = {",
        "type DatabasePack = {",
        'installMode: "manual_external"',
        "operatorActionRequired: true",
        "noAutomaticExecution: true",
        'databaseLayer: "downloadable_pack"',
        "sourceUrl: string",
        "checksum: string",
        "checksumAlgorithm: string",
        "checksumValue: string",
        "archiveSizeBytes: number",
        "installedLayer:",
        "manualInstall: DatabasePackManualInstall",
        "registrationHandoff: DatabasePackRegistrationHandoff",
        "evidencePolicy: DatabasePackEvidencePolicy",
        "databasePackManualText(",
        "databasePackRegistrationCommand(",
        "type DatabasePacksResponse",
        "contractVersion: string",
        "lifecycleContractVersion: string",
        "summary: {",
    )
    _assert_contains(
        api_source,
        "DATABASE_PACKS_CACHE_KEY",
        "fetchDatabasePacks(",
        "getCachedDatabasePacks(",
        "/api/v1/database-packs",
    )
    _assert_contains(
        state_source,
        "packs: DatabasePack[]",
        "packLoading: boolean",
        "packError: string",
        "fetchDatabasePacks(",
        "getCachedDatabasePacks(",
        "const startAddingFromPack",
        'databaseLayer: pack.installedLayer',
        'installationMethod: "manual_external"',
        "installedFromPackId",
    )
    _assert_contains(
        page_source,
        "DatabasePackSection",
        "onStartAddingFromPack={state.startAddingFromPack}",
        "onCopyText={(text) => void state.copyDatabaseText(text)}",
    )
    _assert_contains(
        pack_section_source,
        "databasePackManualText(pack)",
        "databasePackRegistrationCommand(pack)",
        "手动步骤",
        "登记命令",
        "手动登记",
    )
    _assert_not_contains(
        api_source + state_source + page_source + pack_section_source,
        "installDatabasePack",
        "downloadDatabasePack",
        "registerDatabasePack",
    )
    _assert_contains(create_input, 'Exclude<DatabaseLayer, "downloadable_pack" | "unspecified">')
    _assert_not_contains(create_input, 'databaseLayer: "downloadable_pack"', "DatabasePack")


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
        "compositeFallbackPath(compositeFieldValues)",
    )
    _assert_not_contains(source, "Object.values(compositeFieldValues)[0]")


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
        "路径如何传给工具",
        "校验范围",
        "实际工具路径",
        'const actualToolPath = toolPath || (item ? databaseToolPath(item) : "");',
        "copyDatabasePath(toolPath)",
    )
    _assert_not_contains(source, "copyDatabasePath(toolPath || item.path)")


def test_resolved_tool_path_is_explained_when_it_differs_from_selected_path() -> None:
    path_utils_source = _source("path_utils")
    details_source = _source("details")
    state_source = _source("state")

    _assert_in_order(
        path_utils_source,
        'export function databaseToolPath(item: DatabaseItem) {',
        'const resolved = item.resolvedPath;',
        'const entryPath = item.entryPath || item.inputPath || item.path || "";',
        'if (item.pathMode === "prefix") {',
        'return resolved?.prefix || resolved?.path || entryPath;',
        'if (item.pathMode === "directory") {',
        'return entryPath || resolved?.firstIndexPrefix || resolved?.firstMatch || resolved?.path || "";',
        'if (item.pathMode === "file") {',
        'return entryPath || resolved?.path || resolved?.firstMatch || "";',
        'if (item.pathMode === "primary_with_sidecars") {',
        'return entryPath || resolved?.path || resolved?.firstMatch || "";',
        'if (item.pathMode === "composite") {',
        'return "";',
        'return entryPath || resolved?.firstIndexPrefix || resolved?.firstMatch || resolved?.path || "";',
    )

    _assert_not_contains(
        path_utils_source,
        'if (item.pathMode === "composite") {\n    return entryPath;',
        'if (item.pathMode === "composite") {\n    return entryPath || resolved?.path',
    )

    _assert_contains(
        state_source,
        'const path = isComposite ? compositeFallbackPath(compositeFieldValues) : form.path.trim();',
    )
    _assert_not_contains(state_source, 'Object.values(compositeFieldValues)[0]')

    _assert_contains(
        details_source,
        'import type { DatabaseItem } from "./database-page-model";',
        'item: DatabaseItem | null;',
        'const actualToolPath = toolPath || (item ? databaseToolPath(item) : "");',
        'const pathMode = item?.pathMode || item?.resolvedPath?.kind;',
        'const compositeInputText = compositeFieldSummary(item?.input?.fields);',
        'const compositeResolvedText = compositeFieldSummary(item?.resolved);',
        'label="实际工具路径" value={actualToolPath} mono',
        'label="选择路径" value={selectedPath} mono',
        'emptyText="复合数据库由多个字段分别传给工具。"',
        'label="实际工具字段"',
        'emptyText="后端未返回解析后的工具字段。"',
    )

    composite_branch = re.search(r'pathMode === "composite" \?\s*\((.*?)\)\s*:\s*\(', details_source, re.S)
    assert composite_branch is not None
    composite_branch_source = composite_branch.group(1)
    assert 'label="复合输入"' in composite_branch_source
    assert 'label="实际工具字段"' in composite_branch_source
    assert 'label="选择路径"' not in composite_branch_source

    _assert_not_contains(
        details_source,
        "type DatabaseValidationDetailsItem = {",
        'resolvedPath?: {',
        'input?: {',
        'resolved?: Record<string, string>;',
        'item?.entryPath || resolved?.prefix || resolved?.path || selectedPath',
        'item?.entryPath || resolved?.path || resolved?.firstMatch || ""',
        'item?.entryPath || resolved?.firstIndexPrefix || resolved?.firstMatch || resolved?.path || ""',
    )

    _assert_contains(
        path_utils_source,
        "function compositePathSegments(value: string, root: string) {",
        'if (root === "/") {',
        'if (root === "~") {',
        'if (/^[A-Za-z]:(?:\\/|$)/.test(value)) {',
        'if (/^[A-Za-z]:\\/$/.test(root)) {',
        "const root = roots[0].root;",
        'if (roots.some((currentRoot) => currentRoot.kind !== rootKind || currentRoot.root !== root)) {',
        'const segments = normalizedValues.map((value) => compositePathSegments(value, root));',
        'if (root === ".") {',
        'return `${root}${commonSegments.join("/")}`;',
    )
    assert path_utils_source.count("const root = roots[0].root;") == 1


def test_composite_fallback_path_preserves_absolute_roots_at_runtime(tmp_path: Path) -> None:
    script_path = tmp_path / "composite-fallback-path-contract.mjs"
    script_path.write_text(_path_utils_behavior_script(), encoding="utf-8")

    result = subprocess.run(
        ["node", str(script_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


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
