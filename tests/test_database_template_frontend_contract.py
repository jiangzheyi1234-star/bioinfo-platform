from __future__ import annotations

from pathlib import Path


def test_databases_page_does_not_ship_fallback_template_catalog() -> None:
    source = Path("apps/web/app/components/databases-page.tsx").read_text(encoding="utf-8")

    assert "FALLBACK_DATABASE_TEMPLATES" not in source
    assert "setTemplates(FALLBACK" not in source


def test_databases_page_uses_template_path_kind_to_drive_selection_copy() -> None:
    source = Path("apps/web/app/components/databases-page.tsx").read_text(encoding="utf-8")

    assert 'selectorKind: "directory" | "file" | "prefix"' in source
    assert "请选择包含索引文件的目录。" in source
    assert "请选择数据库文件。" in source
    assert "请选择索引前缀或任一索引文件。" in source
    assert '"选所在目录"' in source


def test_databases_page_surfaces_database_validation_messages() -> None:
    source = Path("apps/web/app/components/databases-page.tsx").read_text(encoding="utf-8")

    assert "item.message" in source
    assert "工具验证" in source


def test_databases_page_surfaces_resolved_tool_path_when_it_differs_from_selected_path() -> None:
    source = Path("apps/web/app/components/databases-page.tsx").read_text(encoding="utf-8")

    assert "resolvedPath" in source
    assert "databaseToolPath" in source
    assert "实际工具路径" in source
