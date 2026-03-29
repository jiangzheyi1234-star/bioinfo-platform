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
    if "du -sm" in cmd:
        return 0, "50000\n", ""
    if "cat " in cmd:
        return 0, "", ""
    return 0, "", ""


def _ssh_status_missing(cmd: str, timeout: int = 10):
    del timeout
    if "du -sm" in cmd:
        return 0, "50000\n", ""
    if "status.txt" in cmd:
        return 1, "", ""
    if "test -f" in cmd:
        return 1, "", ""
    return 0, "", ""


def _ssh_missing_key(cmd: str, timeout: int = 10):
    del timeout
    if "du -sm" in cmd:
        return 0, "50000\n", ""
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
    assert db.binding_mode == "directory_root"
    assert svc.get_info("blast_nt").binding_mode == "index_prefix"
    assert svc.get_info("gunc_db").binding_mode == "specific_file"
    assert svc.get_info("gtdb_r220").binding_mode == "env_var_root"
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


def test_resolve_effective_path_prefers_overrides():
    svc = DatabaseService()
    resolved = svc.resolve_effective_path(
        "checkm2_db",
        "/data/databases",
        overrides={"checkm2_db": "/custom/checkm2"},
    )
    assert resolved == "/custom/checkm2"


@pytest.mark.parametrize(
    ("db_id", "db_root", "expected"),
    [
        ("blast_nt", "/data/databases", "/data/databases/blast_nt/nt"),
        ("core_nt", "/data/databases", "/data/databases/core_nt/core_nt"),
        ("centrifuge_hpvc", "/data/databases", "/data/databases/hpvc/hpvc"),
        ("gunc_db", "/data/databases", "/data/databases/gunc/gunc_db_progenomes2.1.dmnd"),
        ("checkm2_db", "/data/databases", "/data/databases/checkm2"),
        ("gtdb_r220", "/data/databases", "/data/databases/gtdbtk/release220"),
    ],
)
def test_resolve_binding_value_by_mode(db_id: str, db_root: str, expected: str):
    svc = DatabaseService()
    assert svc.resolve_binding_value(db_id, db_root) == expected


@pytest.mark.parametrize(
    ("db_id", "raw_path", "expected"),
    [
        ("blast_nt", "/remote/blast_nt", "/remote/blast_nt/nt"),
        ("blast_nt", "/remote/blast_nt/nt", "/remote/blast_nt/nt"),
        ("gunc_db", "/remote/gunc", "/remote/gunc/gunc_db_progenomes2.1.dmnd"),
        ("gunc_db", "/remote/gunc/gunc_db_progenomes2.1.dmnd", "/remote/gunc/gunc_db_progenomes2.1.dmnd"),
    ],
)
def test_canonicalize_binding_value_normalizes_prefix_and_file_modes(db_id: str, raw_path: str, expected: str):
    svc = DatabaseService()
    assert svc.canonicalize_binding_value(db_id, raw_path) == expected


@pytest.mark.parametrize(
    ("db_id", "storage_root", "expected"),
    [
        ("core_nt", "/remote/core_nt", "/remote/core_nt/core_nt"),
        ("centrifuge_hpvc", "/remote/hpvc", "/remote/hpvc/hpvc"),
        ("gunc_db", "/remote/gunc", "/remote/gunc/gunc_db_progenomes2.1.dmnd"),
    ],
)
def test_binding_value_from_storage_root_normalizes_ambiguous_prefix_and_file_modes(
    db_id: str,
    storage_root: str,
    expected: str,
):
    svc = DatabaseService()
    assert svc.binding_value_from_storage_root(db_id, storage_root) == expected


def test_check_status_ready():
    svc = DatabaseService()
    result = svc.check_status(_ssh_all_ok, "kraken2_standard", "/data/databases")
    assert result.status == DatabaseStatus.READY


def test_check_status_uses_override_path():
    calls: list[str] = []

    def fn(cmd: str, timeout: int = 10):
        del timeout
        calls.append(cmd)
        if "du -sm" in cmd:
            return 0, "500000\n", ""
        return 0, "", ""

    svc = DatabaseService()
    result = svc.check_status(
        fn,
        "kraken2_standard",
        "/data/databases",
        overrides={"kraken2_standard": "/custom/kraken2"},
    )
    assert result.status == DatabaseStatus.READY
    assert any("/custom/kraken2" in cmd for cmd in calls)
    assert all("/data/databases/kraken2_standard" not in cmd for cmd in calls)


def test_check_status_canonicalizes_prefix_override_path():
    calls: list[str] = []

    def fn(cmd: str, timeout: int = 10):
        del timeout
        calls.append(cmd)
        if "du -sm" in cmd:
            return 0, "500000\n", ""
        return 0, "", ""

    svc = DatabaseService()
    result = svc.check_status(
        fn,
        "blast_nt",
        "/data/databases",
        overrides={"blast_nt": "/custom/blast_nt"},
    )

    assert result.status == DatabaseStatus.READY
    assert any("/custom/blast_nt/nt" in cmd for cmd in calls)
    assert all("/data/databases/blast_nt/nt" not in cmd for cmd in calls)


def test_check_status_specific_file_checks_file_path():
    calls: list[str] = []

    def fn(cmd: str, timeout: int = 10):
        del timeout
        calls.append(cmd)
        if "du -sm" in cmd:
            return 0, "15000\n", ""
        return 0, "", ""

    svc = DatabaseService()
    result = svc.check_status(
        fn,
        "gunc_db",
        "/data/databases",
    )

    assert result.status == DatabaseStatus.READY
    assert any("test -f" in cmd and "gunc_db_progenomes2.1.dmnd" in cmd for cmd in calls)
    assert any("du -sm" in cmd and "gunc_db_progenomes2.1.dmnd" in cmd for cmd in calls)


def test_check_status_not_installed():
    svc = DatabaseService()
    result = svc.check_status(_ssh_status_missing, "kraken2_standard", "/data/databases")
    assert result.status == DatabaseStatus.NOT_INSTALLED


def test_check_status_incomplete():
    svc = DatabaseService()
    result = svc.check_status(_ssh_missing_key, "kraken2_standard", "/data/databases")
    assert result.status == DatabaseStatus.INCOMPLETE


def test_check_status_reports_small_database():
    def fn(cmd: str, timeout: int = 10):
        del timeout
        if "du -sm" in cmd:
            return 0, "123\n", ""
        return 0, "", ""

    svc = DatabaseService()
    result = svc.check_status(fn, "kraken2_standard", "/data/databases")
    assert result.status == DatabaseStatus.INCOMPLETE
    assert "数据库大小不足" in result.message


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


def test_submit_install_reuses_running_task_when_heartbeat_fresh():
    svc = DatabaseService()
    calls: list[str] = []

    def fn(cmd: str, timeout: int = 10):
        del timeout
        calls.append(cmd)
        if "status.txt" in cmd:
            return 0, "RUNNING\n", ""
        if "exit_code.txt" in cmd:
            return 1, "", ""
        if "heartbeat.txt" in cmd:
            return 0, f"{int(__import__('time').time())}\n", ""
        if "screen -ls" in cmd:
            return 0, "", ""
        return 0, "", ""

    result = svc.submit_install(fn, _caps(), "blast_nt", "/data/databases")

    assert result["reused"] == "1"
    assert not any("screen -dmS" in cmd for cmd in calls)
