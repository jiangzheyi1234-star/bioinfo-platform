from __future__ import annotations

from core.data.database_path_resolver import DatabasePathResolver
from core.data.database_service import DatabaseService


def test_resolve_prefers_overrides():
    resolver = DatabasePathResolver(
        {"db_root": "/data/databases", "overrides": {"kraken2_standard": "/custom/kraken2"}}
    )
    svc = DatabaseService()
    resolved = resolver.resolve("kraken2_standard", "db", svc)
    assert resolved == "/custom/kraken2"


def test_resolve_uses_db_root_with_registry():
    resolver = DatabasePathResolver({"db_root": "/data/databases", "overrides": {}})
    svc = DatabaseService()
    resolved = resolver.resolve("kraken2_standard", "db", svc)
    assert resolved == "/data/databases/kraken2_standard"


def test_resolve_returns_none_when_not_found():
    resolver = DatabasePathResolver({"db_root": "", "overrides": {}})
    svc = DatabaseService()
    resolved = resolver.resolve("kraken2_standard", "db", svc)
    assert resolved is None


def test_expand_tilde_with_ssh_cache():
    calls: list[str] = []

    def fake_ssh(cmd: str, timeout: int = 10):
        del timeout
        calls.append(cmd)
        if "eval echo '~" in cmd:
            return 0, "/home/tester/custom\n", ""
        return 1, "", "unexpected"

    resolver = DatabasePathResolver({"db_root": "", "overrides": {"kraken2_standard": "~/custom"}}, ssh_run_fn=fake_ssh)
    svc = DatabaseService()

    first = resolver.resolve("kraken2_standard", "db", svc)
    second = resolver.resolve("kraken2_standard", "db", svc)

    assert first == "/home/tester/custom"
    assert second == "/home/tester/custom"
    assert len(calls) == 1


def test_expand_tilde_without_ssh_keeps_raw():
    resolver = DatabasePathResolver({"db_root": "", "overrides": {"kraken2_standard": "~/custom"}})
    svc = DatabaseService()
    resolved = resolver.resolve("kraken2_standard", "db", svc)
    assert resolved == "~/custom"
