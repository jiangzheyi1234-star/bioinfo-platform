from __future__ import annotations

from core.remote.runtime_resolution import build_runtime_env_exports, resolve_remote_java, resolve_remote_nextflow


def test_resolve_remote_nextflow_prefers_usable_path_over_conda_fallback() -> None:
    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        _ = timeout
        if 'NF_BIN="$(type -P nextflow 2>/dev/null || true)"' in command:
            return 0, "/usr/local/bin/nextflow\n", ""
        if "/usr/local/bin/nextflow info" in command:
            return 0, "", ""
        if """/usr/local/bin/nextflow -version 2>/dev/null | awk '/version/ {print $NF; exit}'""" in command:
            return 0, "25.04.6\n", ""
        return 1, "", "not found"

    item = resolve_remote_nextflow(ssh_run_fn)

    assert item["usable"] is True
    assert item["command"] == "/usr/local/bin/nextflow"
    assert item["path"] == "/usr/local/bin/nextflow"


def test_resolve_remote_nextflow_uses_fixed_absolute_path_when_path_lookup_is_missing() -> None:
    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        _ = timeout
        if 'NF_BIN="$(type -P nextflow 2>/dev/null || true)"' in command:
            return 0, "", ""
        if 'NF_BIN="$HOME/.local/bin/nextflow"' in command:
            return 0, "/home/tester/.local/bin/nextflow\n", ""
        if "/home/tester/.local/bin/nextflow info" in command:
            return 0, "", ""
        if """/home/tester/.local/bin/nextflow -version 2>/dev/null | awk '/version/ {print $NF; exit}'""" in command:
            return 0, "25.04.6\n", ""
        return 1, "", "not found"

    item = resolve_remote_nextflow(ssh_run_fn)

    assert item["usable"] is True
    assert item["source"] == "fixed_path"
    assert item["command"] == "/home/tester/.local/bin/nextflow"


def test_resolve_remote_java_prefers_nxf_java_home_and_does_not_probe_java_home() -> None:
    seen: list[str] = []

    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        _ = timeout
        seen.append(command)
        if '$NXF_JAVA_HOME/bin/java -version' in command:
            return 0, 'openjdk version "21.0.2" 2024-01-16\n', ""
        return 1, "", "not found"

    item = resolve_remote_java(ssh_run_fn)

    assert item["usable"] is True
    assert item["source"] == "nxf_java_home"
    assert item["home"] == "$NXF_JAVA_HOME"
    assert item["path"] == "$NXF_JAVA_HOME/bin/java"
    assert all("$JAVA_HOME" not in command for command in seen)


def test_resolve_remote_java_derives_absolute_binary_path_from_path_lookup() -> None:
    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        _ = timeout
        if 'if command -v java >/dev/null 2>&1; then java -version' in command:
            return 0, 'openjdk version "21.0.2" 2024-01-16\n', ""
        if 'dirname "$(dirname "$JAVA_BIN")"' in command:
            return 0, "/usr/lib/jvm/java-21-openjdk\n", ""
        if 'readlink -f "$(command -v java)"' in command:
            return 0, "/usr/lib/jvm/java-21-openjdk/bin/java\n", ""
        return 1, "", "not found"

    item = resolve_remote_java(ssh_run_fn)

    assert item["usable"] is True
    assert item["source"] == "path"
    assert item["home"] == "/usr/lib/jvm/java-21-openjdk"
    assert item["path"] == "/usr/lib/jvm/java-21-openjdk/bin/java"


def test_build_runtime_env_exports_only_exports_nxf_java_home() -> None:
    exports = build_runtime_env_exports({"home": "/opt/jdk-21"})

    assert exports == "export NXF_JAVA_HOME=/opt/jdk-21\n"
