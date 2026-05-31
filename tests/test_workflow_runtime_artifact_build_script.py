from __future__ import annotations

import pytest

from scripts.build_workflow_runtime_artifact_on_server import (
    build_remote_script,
    build_remote_script_plan,
    micromamba_platform,
    platform_from_uname,
)


def test_platform_from_uname_maps_supported_linux_architectures() -> None:
    assert platform_from_uname("Linux:x86_64\n") == "linux-64"
    assert platform_from_uname("Linux:aarch64") == "linux-aarch64"
    assert platform_from_uname("Linux:arm64") == "linux-aarch64"


def test_platform_from_uname_rejects_unknown_platform() -> None:
    with pytest.raises(RuntimeError, match="unsupported workflow runtime build platform"):
        platform_from_uname("Darwin:arm64")


def test_micromamba_platform_matches_runtime_platform() -> None:
    assert micromamba_platform("linux-64") == "linux-64"
    assert micromamba_platform("linux-aarch64") == "linux-aarch64"


def test_remote_build_script_uses_target_platform_and_workflow_python_for_manifest() -> None:
    script = build_remote_script(
        version="0.1.0",
        platform="linux-aarch64",
        snakemake_version="9.19.0",
        artifact_name="h2ometa-workflow-runtime-0.1.0-linux-aarch64.tar.gz",
        runtime_source="clean-solve",
        lock_file_name="",
        lock_sha256="",
    )

    assert "https://micro.mamba.pm/api/micromamba/linux-aarch64/latest" in script
    assert "snakemake=9.19.0" in script
    assert '"platform": "linux-aarch64"' in script
    assert '"$BUILD_ROOT/workflow-env-src/bin/python" - <<' in script
    assert "python3 - <<'PY'" not in script


def test_remote_build_script_wraps_conda_pack_activate_for_per_rule_envs() -> None:
    script = build_remote_script(
        version="0.1.0",
        platform="linux-64",
        snakemake_version="9.19.0",
        artifact_name="h2ometa-workflow-runtime-0.1.0-linux-64.tar.gz",
        runtime_source="lockfile",
        lock_file_name="linux-64.explicit.txt",
        lock_sha256="abc123",
    )

    assert 'mv "$BUILD_ROOT/bundle/workflow-env/bin/activate" "$BUILD_ROOT/bundle/workflow-env/bin/activate.conda-pack"' in script
    assert 'PATH="$_h2ometa_activate_dir:$PATH" "$_h2ometa_conda" shell.posix activate "$@"' in script
    assert '. "$_h2ometa_conda_pack_activate"' in script


def test_remote_script_plan_uses_manifest_artifact_name() -> None:
    plan = build_remote_script_plan(
        version="0.1.0",
        platform="linux-64",
        snakemake_version="",
        runtime_source="lockfile",
        lock_file_name="linux-64.explicit.txt",
        lock_sha256="abc123",
    )

    assert plan["artifactName"] == "h2ometa-workflow-runtime-0.1.0-linux-64.tar.gz"
    assert plan["version"] == "0.1.0"
    assert plan["platform"] == "linux-64"
    assert "micromamba create -y -p \"$BUILD_ROOT/workflow-env-src\" --file explicit.txt" in plan["remoteScript"]
    assert '"lockFile": "linux-64.explicit.txt"' in plan["remoteScript"]
    assert '"lockSha256": "abc123"' in plan["remoteScript"]
