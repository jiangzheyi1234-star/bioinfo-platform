from __future__ import annotations

import pytest

from core.data.database_service import DatabaseService, DatabaseStatus
from core.remote.server_capabilities import PreflightError, ServerCapabilities


def _caps(**overrides) -> ServerCapabilities:
    data = {
        "arch": "x86_64",
        "has_curl": True,
        "has_wget": False,
        "has_screen": True,
        "has_sha256sum": True,
        "free_disk_gb": 20.0,
    }
    data.update(overrides)
    return ServerCapabilities(**data)


def _ssh_all_ok(cmd: str, timeout: int = 10):
    del timeout
    if "cat " in cmd:
        return 0, "", ""
    return 0, "", ""


def _ssh_status_missing(cmd: str, timeout: int = 10):
    del timeout
    if "status.txt" in cmd:
        return 1, "", ""
    if "test -f" in cmd:
        return 1, "", ""
    return 0, "", ""


def _ssh_missing_key(cmd: str, timeout: int = 10):
    del timeout
    if "test -f" in cmd:
        return 0, "", ""
    if "test -e" in cmd and "taxo.k2d" in cmd:
        return 1, "", ""
    return 0, "", ""


def test_load_registry():
    svc = DatabaseService()
    db = svc.get_info("kraken2_standard")
    assert db is not None
    assert db.category == "reads"
    assert db.install_path == "kraken2_standard"
    assert svc.get_info("hostile_human_t2t").builtin is True


def test_list_by_category():
    svc = DatabaseService()
    grouped = svc.list_by_category()
    assert "reads" in grouped
    assert any(v.db_id == "kraken2_standard" for v in grouped["reads"])
    assert all(v.db_id != "hostile_human_t2t" for v in svc.list_all())


def test_get_resolved_path():
    svc = DatabaseService()
    resolved = svc.get_resolved_path("checkm2_db", "/data/databases")
    assert resolved == "/data/databases/checkm2"


def test_check_status_ready():
    svc = DatabaseService()
    result = svc.check_status(_ssh_all_ok, "kraken2_standard", "/data/databases")
    assert result.status == DatabaseStatus.READY


def test_check_status_not_installed():
    svc = DatabaseService()
    result = svc.check_status(_ssh_status_missing, "kraken2_standard", "/data/databases")
    assert result.status == DatabaseStatus.NOT_INSTALLED


def test_check_status_incomplete():
    svc = DatabaseService()
    result = svc.check_status(_ssh_missing_key, "kraken2_standard", "/data/databases")
    assert result.status == DatabaseStatus.INCOMPLETE


def test_generate_install_commands_mirror():
    svc = DatabaseService()
    cmds = svc.generate_install_commands(_caps(has_curl=False, has_wget=True), "blast_nt", "/data/databases")
    joined = "\n".join(cmds)
    assert "wget -c --progress=dot:giga" in joined
    assert "touch /data/databases/blast_nt/.install_ok" in joined


def test_generate_install_commands_install_cmd():
    svc = DatabaseService()
    cmds = svc.generate_install_commands(_caps(), "card_db", "/data/databases")
    joined = "\n".join(cmds)
    assert "{{ db_path }}" not in joined
    assert "rgi load --card_json /data/databases/card/card.json --local" in joined


def test_generate_install_commands_uses_curl_when_only_curl_available():
    svc = DatabaseService()
    cmds = svc.generate_install_commands(_caps(has_curl=True, has_wget=False), "blast_nt", "/data/databases")
    joined = "\n".join(cmds)
    assert "curl -fL --progress-bar" in joined
    assert "wget -c --progress=dot:giga" not in joined


def test_parse_progress():
    svc = DatabaseService()
    log = """
         0K .......... .......... .......... ..........  0% 1.2M 3h22m
     50000K .......... .......... .......... .......... 50% 2.1M 1h41m
    """
    parsed = svc.parse_progress(log)
    assert parsed["percent"] == 50
    assert parsed["speed"] == "2.1M/s"
    assert parsed["eta"] == "1h41m"


def test_get_resolved_path_rejects_path_traversal():
    svc = DatabaseService()
    info = svc.get_info("kraken2_standard")
    assert info is not None
    original = info.install_path
    info.install_path = "../etc/passwd"
    try:
        resolved = svc.get_resolved_path("kraken2_standard", "/data/databases")
        assert resolved == ""
    finally:
        info.install_path = original


def test_generate_install_commands_rejects_unsafe_template_syntax():
    svc = DatabaseService()
    info = svc.get_info("card_db")
    assert info is not None
    original = info.install_cmd
    info.install_cmd = "echo {{ ''.__class__ }}"
    try:
        with pytest.raises(ValueError, match="不受支持"):
            svc.generate_install_commands(_caps(), "card_db", "/data/databases")
    finally:
        info.install_cmd = original


def test_submit_install_raises_preflight_error_before_remote_calls():
    svc = DatabaseService()
    calls: list[str] = []

    def fn(cmd: str, timeout: int = 10):
        calls.append(cmd)
        return 0, "", ""

    with pytest.raises(PreflightError, match="screen"):
        svc.submit_install(fn, _caps(has_screen=False), "blast_nt", "/data/databases")

    assert calls == []
