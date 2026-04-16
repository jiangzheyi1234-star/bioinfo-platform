from __future__ import annotations

from core.remote.runtime_resolution import (
    build_runtime_env_exports,
    resolve_persisted_runtime_binding,
    resolve_remote_java,
    resolve_remote_nextflow,
)


def test_resolve_remote_nextflow_prefers_usable_path_over_missing_fixed_candidates() -> None:
    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        _ = timeout
        if 'NF_BIN="$(type -P nextflow 2>/dev/null || true)"' in command:
            return 0, "/usr/local/bin/nextflow\n", ""
        if "/usr/local/bin/nextflow -version 2>/dev/null" in command:
            return 0, "25.04.6\n", ""
        if "/usr/local/bin/nextflow info" in command:
            return 0, "", ""
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
        if "/home/tester/.local/bin/nextflow -version 2>/dev/null" in command:
            return 0, "25.04.6\n", ""
        if "/home/tester/.local/bin/nextflow info" in command:
            return 0, "", ""
        return 1, "", "not found"

    item = resolve_remote_nextflow(ssh_run_fn)

    assert item["usable"] is True
    assert item["source"] == "fixed_path"
    assert item["command"] == "/home/tester/.local/bin/nextflow"


def test_resolve_remote_nextflow_rejects_versions_below_minimum_and_keeps_candidate_list() -> None:
    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        _ = timeout
        if 'NF_BIN="$(type -P nextflow 2>/dev/null || true)"' in command:
            return 0, "/usr/local/bin/nextflow\n", ""
        if "/usr/local/bin/nextflow -version 2>/dev/null" in command:
            return 0, "24.10.0\n", ""
        if "/usr/local/bin/nextflow info" in command:
            return 0, "", ""
        return 1, "", "not found"

    item = resolve_remote_nextflow(ssh_run_fn)

    assert item["available"] is True
    assert item["usable"] is False
    assert item["meets_minimum"] is False
    assert "25.04.0" in item["message"]
    assert item["candidates"][0]["path"] == "/usr/local/bin/nextflow"
    assert item["candidates"][0]["usable"] is False


def test_resolve_remote_nextflow_marks_agent_mode_support_for_recommended_versions() -> None:
    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        _ = timeout
        if 'NF_BIN="$(type -P nextflow 2>/dev/null || true)"' in command:
            return 0, "/usr/local/bin/nextflow\n", ""
        if "/usr/local/bin/nextflow -version 2>/dev/null" in command:
            return 0, "26.04.1\n", ""
        if "/usr/local/bin/nextflow info" in command:
            return 0, "", ""
        return 1, "", "not found"

    item = resolve_remote_nextflow(ssh_run_fn)

    assert item["usable"] is True
    assert item["recommended"] is True
    assert item["agent_mode_supported"] is True
    assert item["upgrade_recommended"] is False


def test_resolve_remote_java_uses_path_lookup_without_probing_nxf_java_home() -> None:
    seen: list[str] = []

    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        _ = timeout
        seen.append(command)
        if 'JAVA_BIN="$(type -P java 2>/dev/null || true)"' in command:
            return 0, "/usr/lib/jvm/java-21-openjdk/bin/java\n", ""
        if "/usr/lib/jvm/java-21-openjdk/bin/java -version" in command:
            return 0, 'openjdk version "21.0.2" 2024-01-16\n', ""
        if 'dirname "$(dirname "$JAVA_BIN")"' in command and "/usr/lib/jvm/java-21-openjdk/bin/java" in command:
            return 0, "/usr/lib/jvm/java-21-openjdk\n", ""
        return 1, "", "not found"

    item = resolve_remote_java(ssh_run_fn)

    assert item["usable"] is True
    assert item["source"] == "path"
    assert item["home"] == "/usr/lib/jvm/java-21-openjdk"
    assert item["path"] == "/usr/lib/jvm/java-21-openjdk/bin/java"


def test_resolve_remote_java_prefers_nxf_java_home_over_path() -> None:
    seen: list[str] = []

    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        _ = timeout
        seen.append(command)
        if 'if [ -n "${NXF_JAVA_HOME:-}" ]' in command:
            return 0, "/home/tester/nxf-java/bin/java\n", ""
        if "/home/tester/nxf-java/bin/java -version" in command:
            return 0, 'openjdk version "21.0.2" 2024-01-16\n', ""
        if 'dirname "$(dirname "$JAVA_BIN")"' in command and "/home/tester/nxf-java/bin/java" in command:
            return 0, "/home/tester/nxf-java\n", ""
        raise AssertionError(f"unexpected command: {command}")

    item = resolve_remote_java(ssh_run_fn)

    assert item["usable"] is True
    assert item["source"] == "nxf_java_home"
    assert item["home"] == "/home/tester/nxf-java"
    assert item["path"] == "/home/tester/nxf-java/bin/java"
    assert all('type -P java' not in command for command in seen)


def test_resolve_remote_java_uses_java_home_when_nxf_java_home_is_missing() -> None:
    seen: list[str] = []

    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        _ = timeout
        seen.append(command)
        if 'if [ -n "${NXF_JAVA_HOME:-}" ]' in command:
            return 0, "", ""
        if 'if [ -n "${JAVA_HOME:-}" ]' in command:
            return 0, "/home/tester/java-home/bin/java\n", ""
        if "/home/tester/java-home/bin/java -version" in command:
            return 0, 'openjdk version "21.0.2" 2024-01-16\n', ""
        if 'dirname "$(dirname "$JAVA_BIN")"' in command and "/home/tester/java-home/bin/java" in command:
            return 0, "/home/tester/java-home\n", ""
        raise AssertionError(f"unexpected command: {command}")

    item = resolve_remote_java(ssh_run_fn)

    assert item["usable"] is True
    assert item["source"] == "java_home"
    assert item["home"] == "/home/tester/java-home"
    assert item["path"] == "/home/tester/java-home/bin/java"
    assert all('type -P java' not in command for command in seen)


def test_resolve_remote_java_derives_absolute_binary_path_from_path_lookup() -> None:
    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        _ = timeout
        if 'JAVA_BIN="$(type -P java 2>/dev/null || true)"' in command:
            return 0, "/usr/lib/jvm/java-21-openjdk/bin/java\n", ""
        if "/usr/lib/jvm/java-21-openjdk/bin/java -version" in command:
            return 0, 'openjdk version "21.0.2" 2024-01-16\n', ""
        if 'dirname "$(dirname "$JAVA_BIN")"' in command and "/usr/lib/jvm/java-21-openjdk/bin/java" in command:
            return 0, "/usr/lib/jvm/java-21-openjdk\n", ""
        return 1, "", "not found"

    item = resolve_remote_java(ssh_run_fn)

    assert item["usable"] is True
    assert item["source"] == "path"
    assert item["home"] == "/usr/lib/jvm/java-21-openjdk"
    assert item["path"] == "/usr/lib/jvm/java-21-openjdk/bin/java"


def test_resolve_remote_java_uses_sdkman_candidate_when_path_lookup_is_missing() -> None:
    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        _ = timeout
        if 'if [ -n "${NXF_JAVA_HOME:-}" ]' in command:
            return 0, "", ""
        if 'if [ -n "${JAVA_HOME:-}" ]' in command:
            return 0, "", ""
        if 'JAVA_BIN="$(type -P java 2>/dev/null || true)"' in command:
            return 0, "", ""
        if 'JAVA_BIN="$HOME/.sdkman/candidates/java/current/bin/java"' in command:
            return 0, "/home/tester/.sdkman/candidates/java/current/bin/java\n", ""
        if "/home/tester/.sdkman/candidates/java/current/bin/java -version" in command:
            return 0, 'openjdk version "21.0.2" 2024-01-16\n', ""
        if 'dirname "$(dirname "$JAVA_BIN")"' in command and "/home/tester/.sdkman/candidates/java/current/bin/java" in command:
            return 0, "/home/tester/.sdkman/candidates/java/current\n", ""
        return 1, "", "not found"

    item = resolve_remote_java(ssh_run_fn)

    assert item["usable"] is True
    assert item["source"] == "sdkman_current"
    assert item["home"] == "/home/tester/.sdkman/candidates/java/current"
    assert item["path"] == "/home/tester/.sdkman/candidates/java/current/bin/java"


def test_build_runtime_env_exports_only_exports_nxf_java_home() -> None:
    exports = build_runtime_env_exports({"home": "/opt/jdk-21"})

    assert exports == "export NXF_JAVA_HOME=/opt/jdk-21\n"


def test_resolve_persisted_runtime_binding_uses_saved_fixed_paths_only() -> None:
    seen: list[str] = []

    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        _ = timeout
        seen.append(command)
        if "/opt/nextflow/nextflow -version" in command:
            return 0, "26.04.1\n", ""
        if "/opt/nextflow/nextflow info" in command:
            return 0, "", ""
        if "/opt/jdk-21/bin/java -version" in command:
            return 0, 'openjdk version "21.0.2" 2024-01-16\n', ""
        return 1, "", "not found"

    item = resolve_persisted_runtime_binding(
        ssh_run_fn,
        {
            "verification_status": "verified",
            "nextflow_path": "/opt/nextflow/nextflow",
            "nextflow_command": "/opt/nextflow/nextflow",
            "java_path": "/opt/jdk-21/bin/java",
            "java_home": "/opt/jdk-21",
        },
    )

    assert item["nextflow_command"] == "/opt/nextflow/nextflow"
    assert item["java_home"] == "/opt/jdk-21"
    assert item["agent_mode_supported"] is True
    assert all("command -v java" not in command for command in seen)
    assert all("type -P nextflow" not in command for command in seen)


def test_resolve_persisted_runtime_binding_requires_verified_saved_state() -> None:
    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        raise AssertionError(f"unexpected command: {command}")

    try:
        resolve_persisted_runtime_binding(
            ssh_run_fn,
            {
                "verification_status": "failed",
                "nextflow_path": "/opt/nextflow/nextflow",
                "java_home": "/opt/jdk-21",
            },
        )
    except RuntimeError as exc:
        assert "未完成验证" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected RuntimeError")
