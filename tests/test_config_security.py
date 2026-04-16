from __future__ import annotations

import json
from pathlib import Path

import config
import pytest


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


def _read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_save_config_stores_ssh_password_in_keyring(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    fake_keyring = FakeKeyring()
    monkeypatch.setattr(config, "_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(config, "_load_keyring_backend", lambda: fake_keyring)

    schema = config.default_settings_schema()
    schema["ssh"]["host"] = "10.0.0.2"
    schema["ssh"]["user"] = "root"
    schema["ssh"]["password"] = "super-secret"

    config.save_config(schema)

    stored = _read_json(cfg_path)
    assert stored["ssh"]["host"] == "10.0.0.2"
    assert stored["ssh"]["user"] == "root"
    assert stored["ssh"]["password"] == ""
    assert stored["ssh"]["password_ref"] == "ssh://root@10.0.0.2:22"
    assert fake_keyring.values[(config._SSH_KEYRING_SERVICE, "ssh://root@10.0.0.2:22")] == "super-secret"


def test_get_config_migrates_plaintext_ssh_password(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    fake_keyring = FakeKeyring()
    monkeypatch.setattr(config, "_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(config, "_load_keyring_backend", lambda: fake_keyring)

    schema = config.default_settings_schema()
    schema["ssh"]["host"] = "10.0.0.8"
    schema["ssh"]["user"] = "ubuntu"
    schema["ssh"]["password"] = "legacy-secret"
    cfg_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")

    loaded = config.get_config()
    stored = _read_json(cfg_path)

    assert loaded["ssh"]["password"] == ""
    assert stored["ssh"]["password"] == ""
    assert stored["ssh"]["password_ref"] == "ssh://ubuntu@10.0.0.8:22"
    assert config.resolve_ssh_password(stored["ssh"]) == "legacy-secret"


def test_normalize_config_rejects_legacy_config():
    legacy = {
        "ip": "192.168.1.8",
        "user": "ubuntu",
        "pwd": "legacy-secret",
        "ssh_port": 22,
    }

    with pytest.raises(ValueError, match="legacy config format is no longer supported"):
        config.normalize_config(legacy)


def test_resolve_ssh_password_reads_keyring_reference(monkeypatch):
    fake_keyring = FakeKeyring()
    fake_keyring.set_password(config._SSH_KEYRING_SERVICE, "ssh://tester@example:2200", "stored-secret")
    monkeypatch.setattr(config, "_load_keyring_backend", lambda: fake_keyring)

    ssh = {
        "host": "example",
        "port": 2200,
        "user": "tester",
        "password": "",
        "password_ref": "ssh://tester@example:2200",
        "use_key": False,
        "key_file": "",
    }

    assert config.resolve_ssh_password(ssh) == "stored-secret"


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


def test_normalize_config_rejects_non_mapping_database_overrides():
    data = config.default_settings_schema()
    data["databases"] = {
        "db_root": "/data/databases",
        "overrides": ["/custom/kraken2"],
    }

    with pytest.raises(ValueError, match="legacy config format is no longer supported"):
        config.normalize_config(data)


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
    fake_keyring = FakeKeyring()
    monkeypatch.setattr(config, "_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(config, "_load_keyring_backend", lambda: fake_keyring)

    schema = config.default_settings_schema()
    schema["linux"]["auto_installed"] = True
    schema["runtime"]["conda_profiles"] = {"stale": {"conda_executable": "/tmp/conda"}}

    config.save_config(schema)
    stored = _read_json(cfg_path)

    assert "auto_installed" not in stored["linux"]
    assert "conda_profiles" not in stored["runtime"]


def test_runtime_resolved_schema_persists_fixed_runtime_and_project_task_paths(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    fake_keyring = FakeKeyring()
    monkeypatch.setattr(config, "_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(config, "_load_keyring_backend", lambda: fake_keyring)

    schema = config.default_settings_schema()
    schema["runtime"]["resolved"].update(
        {
            "host_key": "ssh://tester@example:22",
            "selected_profile": "personal_docker",
            "resolved_at": "2026-04-16T08:30:00Z",
            "verification_status": "verified",
            "bash_path": "/usr/bin/bash",
            "nextflow_path": "/opt/nextflow/nextflow",
            "nextflow_command": "/opt/nextflow/nextflow",
            "nextflow_source": "fixed_path",
            "nextflow_message": "已检测到 Nextflow，可直接使用",
            "java_path": "/opt/jdk-21/bin/java",
            "java_home": "/opt/jdk-21",
            "java_message": "已检测到 Java，可用于运行 Nextflow",
            "project_id": "proj_demo",
            "task_id": "task_prepare",
            "pipeline_id": "nf_rnaseq",
            "pipeline_entry": "/srv/h2ometa/pipelines/nf_rnaseq/main.nf",
            "pipeline_repo_dir": "/srv/h2ometa/pipelines",
            "project_dir": "/srv/h2ometa/projects/proj_demo",
            "work_dir": "/srv/h2ometa/projects/proj_demo/work",
            "results_dir": "/srv/h2ometa/projects/proj_demo/results",
        }
    )

    config.save_config(schema)
    stored = _read_json(cfg_path)
    loaded = config.get_config()

    assert stored["runtime"]["resolved"]["pipeline_entry"] == "/srv/h2ometa/pipelines/nf_rnaseq/main.nf"
    assert stored["runtime"]["resolved"]["pipeline_repo_dir"] == "/srv/h2ometa/pipelines"
    assert stored["runtime"]["resolved"]["project_dir"] == "/srv/h2ometa/projects/proj_demo"
    assert stored["runtime"]["resolved"]["work_dir"] == "/srv/h2ometa/projects/proj_demo/work"
    assert stored["runtime"]["resolved"]["results_dir"] == "/srv/h2ometa/projects/proj_demo/results"
    assert loaded["runtime"]["resolved"]["project_id"] == "proj_demo"
    assert loaded["runtime"]["resolved"]["task_id"] == "task_prepare"


def test_runtime_resolved_schema_drops_unknown_fields():
    data = config.default_settings_schema()
    data["runtime"]["resolved"]["unexpected"] = "nope"

    normalized = config.normalize_config(data)

    assert "unexpected" not in normalized["runtime"]["resolved"]
