from __future__ import annotations

from ui.main_window import MainWindow


def test_has_legacy_database_config_detects_extra_keys():
    raw = {"databases": {"db_root": "/data/databases", "overrides": {}, "blast_nt": "/legacy/path"}}
    assert MainWindow._has_legacy_database_config(raw) is True


def test_has_legacy_database_config_accepts_latest_structure():
    raw = {"databases": {"db_root": "/data/databases", "overrides": {"kraken2_standard": "/custom"}}}
    assert MainWindow._has_legacy_database_config(raw) is False


def test_has_legacy_database_config_rejects_invalid_overrides_type():
    raw = {"databases": {"db_root": "/data/databases", "overrides": "/not-a-dict"}}
    assert MainWindow._has_legacy_database_config(raw) is True
