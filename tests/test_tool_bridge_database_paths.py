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
        "command_template": "kraken2 --db {{ db }}",
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
        "command_template": "kraken2 --db {{ db }}",
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


def test_build_database_paths_resolves_builtin_bind_only_database(monkeypatch):
    descriptor = {
        "command_template": "centrifuge -x {{ db }}",
        "databases": [
            {"id": "centrifuge_hpvc", "param_name": "db", "required": True},
        ]
    }
    service = ToolBridgeService(plugin_registry=_FakeRegistry(descriptor))

    monkeypatch.setattr(
        "config.get_config",
        lambda: {"databases": {"db_root": "/data/databases", "overrides": {}}},
    )

    paths = service.build_database_paths("centrifuge")
    assert paths["db"] == "/data/databases/hpvc/hpvc"


def test_build_database_paths_returns_blast_prefix(monkeypatch):
    descriptor = {
        "command_template": "blastn -db {{ db }} -query {{ query }}",
        "databases": [
            {"id": "blast_nt", "param_name": "db", "required": True},
        ],
    }
    service = ToolBridgeService(plugin_registry=_FakeRegistry(descriptor))

    monkeypatch.setattr(
        "config.get_config",
        lambda: {"databases": {"db_root": "/data/databases", "overrides": {}}},
    )

    paths = service.build_database_paths("blastn")
    assert paths["db"] == "/data/databases/blast_nt/nt"


def test_build_database_paths_returns_specific_file_binding(monkeypatch):
    descriptor = {
        "command_template": "gunc run --db_file {{ db }}",
        "databases": [
            {"id": "gunc_db", "param_name": "db", "required": True},
        ],
    }
    service = ToolBridgeService(plugin_registry=_FakeRegistry(descriptor))

    monkeypatch.setattr(
        "config.get_config",
        lambda: {"databases": {"db_root": "/data/databases", "overrides": {}}},
    )

    paths = service.build_database_paths("gunc")
    assert paths["db"] == "/data/databases/gunc/gunc_db_progenomes2.1.dmnd"


def test_build_database_paths_raises_for_unknown_registry_db_id(monkeypatch):
    descriptor = {
        "command_template": "blastn -db {{ db }}",
        "databases": [
            {"id": "missing_db", "param_name": "db", "required": True},
        ]
    }
    service = ToolBridgeService(plugin_registry=_FakeRegistry(descriptor))

    monkeypatch.setattr(
        "config.get_config",
        lambda: {"databases": {"db_root": "/data/databases", "overrides": {}}},
    )

    with pytest.raises(ValueError, match="blastn.*missing_db"):
        service.build_database_paths("blastn")


def test_build_database_paths_ignores_legacy_flat_config(monkeypatch):
    descriptor = {
        "command_template": "blastn -db {{ db }}",
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
    assert paths == {}


def test_build_database_paths_raises_when_database_decl_not_consumed(monkeypatch):
    descriptor = {
        "command_template": "rgi main --input_sequence {{ contigs }}",
        "databases": [
            {"id": "card_db", "param_name": "db", "required": True},
        ],
    }
    service = ToolBridgeService(plugin_registry=_FakeRegistry(descriptor))

    monkeypatch.setattr(
        "config.get_config",
        lambda: {"databases": {"db_root": "/data/databases", "overrides": {}}},
    )

    with pytest.raises(ValueError, match="命令模板未消费"):
        service.build_database_paths("rgi")
