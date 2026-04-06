from __future__ import annotations

import json
from pathlib import Path

import config
import pytest


def _read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_save_config_persists_ssh_password(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(config, "_CONFIG_PATH", cfg_path)

    schema = config.default_settings_schema()
    schema["ssh"]["host"] = "10.0.0.2"
    schema["ssh"]["user"] = "root"
    schema["ssh"]["password"] = "super-secret"

    config.save_config(schema)

    stored = _read_json(cfg_path)
    assert stored["ssh"]["host"] == "10.0.0.2"
    assert stored["ssh"]["user"] == "root"
    assert stored["ssh"]["password"] == "super-secret"


def test_normalize_config_rejects_legacy_config():
    legacy = {
        "ip": "192.168.1.8",
        "user": "ubuntu",
        "pwd": "legacy-secret",
        "ssh_port": 22,
    }

    with pytest.raises(ValueError, match="legacy config format is no longer supported"):
        config.normalize_config(legacy)


def test_normalize_config_keeps_password_field():
    data = config.default_settings_schema()
    data["ssh"]["password"] = "should-survive"

    normalized = config.normalize_config(data)

    assert normalized["ssh"]["password"] == "should-survive"


def test_normalize_config_rejects_legacy_flat_databases():
    data = config.default_settings_schema()
    data["databases"] = {
        "kraken2": "/db/kraken2",
        "checkm2": "",
        "blast_nt": "/db/blast_nt",
    }

    with pytest.raises(ValueError, match="legacy config format is no longer supported"):
        config.normalize_config(data)


def test_normalize_config_keeps_structured_databases():
    data = config.default_settings_schema()
    data["databases"] = {
        "db_root": "/data/databases",
        "overrides": {"kraken2": "/custom/kraken2"},
    }

    normalized = config.normalize_config(data)

    assert normalized["databases"]["db_root"] == "/data/databases"
    assert normalized["databases"]["overrides"]["kraken2"] == "/custom/kraken2"


def test_default_schema_omits_removed_linux_and_runtime_fields():
    schema = config.default_settings_schema()
    assert "auto_installed" not in schema["linux"]
    assert "conda_profiles" not in schema["runtime"]


def test_normalize_config_drops_removed_linux_and_runtime_fields():
    data = config.default_settings_schema()
    data["linux"]["auto_installed"] = True
    data["runtime"]["conda_profiles"] = {"stale": {"conda_executable": "/tmp/conda"}}

    normalized = config.normalize_config(data)

    assert "auto_installed" not in normalized["linux"]
    assert "conda_profiles" not in normalized["runtime"]


def test_save_config_omits_removed_linux_and_runtime_fields(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(config, "_CONFIG_PATH", cfg_path)

    schema = config.default_settings_schema()
    schema["linux"]["auto_installed"] = True
    schema["runtime"]["conda_profiles"] = {"stale": {"conda_executable": "/tmp/conda"}}

    config.save_config(schema)
    stored = _read_json(cfg_path)

    assert "auto_installed" not in stored["linux"]
    assert "conda_profiles" not in stored["runtime"]
