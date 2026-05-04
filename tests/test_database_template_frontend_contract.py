from __future__ import annotations

from pathlib import Path


def _databases_page_contract_source() -> str:
    return "\n".join(
        [
            Path("apps/web/app/components/databases-page.tsx").read_text(encoding="utf-8"),
            Path("apps/web/app/components/databases-add-panel.tsx").read_text(encoding="utf-8"),
            Path("apps/web/app/components/databases-item-list.tsx").read_text(encoding="utf-8"),
            Path("apps/web/app/components/use-databases-page-state.ts").read_text(encoding="utf-8"),
            Path("apps/web/app/components/database-page-api.ts").read_text(encoding="utf-8"),
            Path("apps/web/app/components/database-page-model.ts").read_text(encoding="utf-8"),
            Path("apps/web/app/components/database-page-ui.tsx").read_text(encoding="utf-8"),
            Path("apps/web/app/components/database-path-utils.ts").read_text(encoding="utf-8"),
        ]
    )


def test_databases_page_does_not_ship_fallback_template_catalog() -> None:
    source = _databases_page_contract_source()

    assert "FALLBACK_DATABASE_TEMPLATES" not in source
    assert "setTemplates(FALLBACK" not in source


def test_databases_page_uses_template_path_kind_to_drive_selection_copy() -> None:
    source = _databases_page_contract_source()

    assert 'type PathKind = "directory" | "file" | "prefix" | "primary_with_sidecars" | "composite"' in source
    assert "fields?: Record<string, DatabaseTemplateField>" in source
    assert "选择${pathLabel(template)}" in source
    assert "运行时直接注入该目录。" in source
    assert "运行时直接注入该文件。" in source
    assert "运行时注入去掉索引后缀后的 prefix。" in source
    assert "运行时注入 FASTA 主文件，并检查同名前缀索引。" in source
    assert "不要选择旁边的索引文件。" in source
    assert "工具入口路径" not in source
    assert "数据库目录" in source
    assert "数据库文件" in source
    assert "索引目录或索引文件" in source
    assert "FASTA 主文件" in source
    assert "template?.pathLabel" in source
    assert "templateCheckItems(" in source
    assert "复合数据库暂未支持，请先使用单路径模板。" not in source
    assert "复合数据库需要填写多个路径字段。" in source
    assert "runtimeValue" in source
    assert "supportLevel?: \"stable\"" in source
    assert "stableComplexityCopy(" in source
    assert "Stable · 复合数据库" in source
    assert "Stable · 高级路径解析" in source
    assert "选择目标" in source
    assert "自动校验" in source
    assert "路径示例" in source
    assert "runtimeHint(" in source
    assert "templateCheckItemList(" in source
    assert "工具实际使用什么" not in source
    assert "会怎样验证" not in source
    assert '"选所在目录"' not in source
    assert 'item.isDirectory ? "进入"' not in source
    assert "进入" in source
    assert "选择当前目录" in source
    assert 'onClick={() => selectBrowserPath(browserPath)}' in source
    assert "选择当前目录" in source
    assert "选择此文件" in source
    assert "选择此索引" in source
    assert "选择 FASTA 主文件" in source
    assert "索引文件不能作为 FASTA 主文件" in source
    assert r"\.(amb|ann|bwt|pac|sa)$" in source
    assert "选择文件/索引" not in source
    assert 'item.isDirectory ? void loadRemotePath(item.path)' in source
    assert "browserSelectionPath" not in source
    assert "stripIndexSuffix" not in source
    assert "onClick={() => selectBrowserPath(item.path)}" in source


def test_databases_page_renders_and_submits_composite_fields() -> None:
    source = _databases_page_contract_source()

    assert "compositeFields" in source
    assert "compositeFieldEntries(" in source
    assert "updateCompositeField(" in source
    assert "selectBrowserPathForCompositeField(" in source
    assert "metadataInput" in source
    assert "kind: \"multi\"" in source
    assert "fields: compositeInputFields" in source
    assert "compositeReady" in source
    assert "ChocoPhlAn 目录" in source or "field.label" in source


def test_databases_page_surfaces_database_validation_messages() -> None:
    source = _databases_page_contract_source()

    assert "item.message" in source
    assert "工具验证" in source


def test_databases_page_surfaces_resolved_tool_path_when_it_differs_from_selected_path() -> None:
    source = _databases_page_contract_source()

    assert "resolvedPath" in source
    assert "databaseToolPath" in source
    assert "实际工具路径" in source
    assert 'resolved?.kind === "prefix"' in source
    assert 'resolved?.kind === "file"' in source
    assert 'resolved?.kind === "directory"' in source
    assert 'resolved?.kind === "primary_with_sidecars"' in source
    assert "resolved.firstIndexPrefix || resolved.firstMatch || resolved.path" in source
    assert "resolved?.firstIndexPrefix || resolved?.firstMatch || resolved?.path" in source
    assert "availableReadLengths" in Path("apps/web/app/components/database-validation-details-dialog.tsx").read_text(encoding="utf-8")


def test_databases_page_exposes_validation_details_dialog() -> None:
    page_source = _databases_page_contract_source()
    details_source = Path("apps/web/app/components/database-validation-details-dialog.tsx").read_text(encoding="utf-8")

    assert "查看校验详情" in page_source
    assert "DatabaseValidationDetailsDialog" in page_source
    assert "数据库路径" in details_source
    assert "校验结果" in details_source
    assert "工具探测输出" in details_source
    assert "工具探测：" in details_source
    assert "通过" in details_source
    assert "失败" in details_source
    assert "未配置" in details_source
    assert "未捕获 stdout" in details_source
    assert "未捕获 stderr" in details_source
    assert "该模板未配置工具探测" in details_source
    assert "实际执行命令" in details_source
    assert "返回码" in details_source
    assert "stdout" in details_source
    assert "stderr" in details_source
    assert "路径如何传给工具" in details_source
    assert "去掉索引后缀的 prefix" in details_source
    assert "FASTA 主文件" in details_source


def test_databases_page_does_not_treat_declared_database_as_validated() -> None:
    source = _databases_page_contract_source()

    assert 'item.status === "declared"' in source
    assert "未校验" in source
    assert 'if (database.status !== "available")' in source
    assert 'throw new Error(database.message || "数据库添加接口未返回可用状态。")' in source
    assert "ensureDatabaseAvailable" not in source


def test_databases_page_keeps_browser_navigation_separate_from_selected_path() -> None:
    source = _databases_page_contract_source()

    assert "type PathSelectionMode = \"none\" | \"browser\" | \"manual\"" in source
    assert "selectionMode" in source
    assert "selectBrowserPath(" in source
    assert "editManualPath(" in source
    assert 'path: "",' in source
    assert "setSelectionMode(\"none\")" in source
    assert "loadRemotePath(item.path)" in source
    assert "onClick={() => selectBrowserPath(item.path)}" in source
    assert "browserSelectionPath" not in source
    assert "已选择：" in source


def test_databases_page_explains_add_validation_before_saving() -> None:
    source = _databases_page_contract_source()

    assert "加入前会解析入口路径并运行模板检查；验证失败不会保存为可用数据库。" in source


def test_databases_page_uses_stable_unique_keys_for_repeated_check_items() -> None:
    source = _databases_page_contract_source()

    assert ".map((item, index) =>" in source
    assert "key={`${item}-${index}`}" in source
    assert "key={item}" not in source


def test_databases_page_uses_asset_registration_language_and_grouped_types() -> None:
    source = _databases_page_contract_source()

    assert "数据库类型" in source
    assert "选择模板" not in source
    assert "分类学数据库" in source
    assert "比对索引" in source
    assert "注释数据库" in source
    assert 'category: "taxonomy"' in source
    assert 'category: "alignment"' in source
    assert 'category: "annotation"' in source
    assert "function templateCategory(" in source
    assert "templateCategory(template) === group.category" in source
    assert 'template.type === "sequence_index"' in source
    assert "数据库名称" in source
    assert "Kraken2 Standard 2024" in source
    assert "校验并保存" in source
    assert "加入中" not in source
    assert "{saving ? \"校验中\" : \"校验并保存\"}" in source


def test_databases_page_keeps_add_form_visible_while_type_list_scrolls() -> None:
    source = _databases_page_contract_source()

    assert "max-h-[calc(100vh-13rem)]" in source
    assert "overflow-y-auto pr-2" in source
    assert "md:sticky" in source
    assert "md:top-16" in source
    assert "md:max-h-[calc(100vh-8rem)]" not in source
    assert "md:overflow-y-auto" not in source
    assert "max-h-64 overflow-auto" not in source
    assert "max-h-80 overflow-y-auto" in source
    assert "REMOTE_BROWSER_PAGE_SIZE = 500" in source
    assert "offset=${offset}" in source
    assert "加载更多" in source
    assert "已分批加载" in source
    assert "handleBrowserScroll" in source
    assert "onScroll={handleBrowserScroll}" in source
    assert "detectedPrefixCandidates(" not in source
    assert "detectedFileCandidates(" not in source
    assert "detectedPrimaryCandidates(" not in source
    assert "detectedTargetCandidates(" not in source
    assert "detectedOtherTemplateTargets(" not in source
    assert "selectDetectedTarget(" not in source
    assert "检测到可用 prefix" not in source
    assert "检测到可用数据库文件" not in source
    assert "检测到可用主文件" not in source
    assert "当前目录更像其他数据库类型" not in source
    assert "切换并选择" not in source
    assert "candidateDetailFromError(" in source
    assert "请选择数据库入口" in source
    assert "selectedEntryPath" in source
