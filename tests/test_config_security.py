from __future__ import annotations

import json
from pathlib import Path

import config


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


def test_migrate_legacy_config_keeps_password():
    legacy = {
        "ip": "192.168.1.8",
        "user": "ubuntu",
        "pwd": "legacy-secret",
        "ssh_port": 22,
    }

    migrated = config.migrate_legacy_config(legacy)

    assert migrated["ssh"]["host"] == "192.168.1.8"
    assert migrated["ssh"]["user"] == "ubuntu"
    assert migrated["ssh"]["password"] == "legacy-secret"


def test_normalize_config_keeps_password_field():
    data = config.default_settings_schema()
    data["ssh"]["password"] = "should-survive"

    normalized = config.normalize_config(data)

    assert normalized["ssh"]["password"] == "should-survive"
