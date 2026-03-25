from __future__ import annotations

import pytest

from core.execution.tool_bridge_service import ToolBridgeService


class _FakeRegistry:
    def __init__(self, descriptor: dict):
        self._descriptor = descriptor

    def get_descriptor(self, tool_id: str):
        del tool_id
        return self._descriptor


def test_build_database_paths_prefers_overrides(monkeypatch):
    descriptor = {
        "databases": [
            {"id": "kraken2_standard", "param_name": "db", "required": True},
        ]
    }
    service = ToolBridgeService(plugin_registry=_FakeRegistry(descriptor))

    monkeypatch.setattr(
        "config.get_config",
        lambda: {"databases": {"db_root": "/data/databases", "overrides": {"kraken2_standard": "/custom/kraken2"}}},
    )

    paths = service.build_database_paths("kraken2")
    assert paths["db"] == "/custom/kraken2"


def test_build_database_paths_uses_db_root_with_registry(monkeypatch):
    descriptor = {
        "databases": [
            {"id": "kraken2_standard", "param_name": "db", "required": True},
        ]
    }
    service = ToolBridgeService(plugin_registry=_FakeRegistry(descriptor))

    monkeypatch.setattr(
        "config.get_config",
        lambda: {"databases": {"db_root": "/data/databases", "overrides": {}}},
    )

    paths = service.build_database_paths("kraken2")
    assert paths["db"] == "/data/databases/kraken2_standard"


def test_build_database_paths_no_legacy_flat_fallback(monkeypatch):
    descriptor = {
        "databases": [
            {"id": "blast_nt", "param_name": "db", "required": True},
        ]
    }
    service = ToolBridgeService(plugin_registry=_FakeRegistry(descriptor))

    monkeypatch.setattr(
        "config.get_config",
        lambda: {"databases": {"blast_nt": "/legacy/blast_nt"}},
    )

    paths = service.build_database_paths("blastn")
    assert "db" not in paths


def test_build_database_paths_ignores_legacy_override_key(monkeypatch):
    descriptor = {
        "databases": [
            {"id": "kraken2_standard", "param_name": "db", "required": True},
        ]
    }
    service = ToolBridgeService(plugin_registry=_FakeRegistry(descriptor))

    monkeypatch.setattr(
        "config.get_config",
        lambda: {"databases": {"db_root": "/data/databases", "overrides": {"kraken2": "/legacy/kraken2"}}},
    )

    paths = service.build_database_paths("kraken2")
    assert paths["db"] == "/data/databases/kraken2_standard"


def test_validate_required_databases_error_message_includes_guidance():
    descriptor = {
        "databases": [
            {"id": "kraken2_standard", "param_name": "db", "required": True},
        ]
    }
    with pytest.raises(ValueError) as exc:
        ToolBridgeService.validate_required_databases(descriptor, {})
    message = str(exc.value)
    assert "数据库路径未匹配" in message
    assert "overrides 是否使用 db_id 作为 key" in message
    assert "数据库管理 > ⚙️ 设置" in message
