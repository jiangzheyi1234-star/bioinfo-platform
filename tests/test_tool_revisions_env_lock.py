from __future__ import annotations

from apps.remote_runner.tool_revisions import build_environment_lock, tool_spec_hash


def test_tool_spec_hash_includes_environment_lock():
    tool1 = {
        "id": "tool1",
        "source": "bioconda",
        "version": "1.0",
        "packageSpec": "tool=1.0",
        "environmentLock": {"adapter": "conda", "name": "env1"},
    }
    tool2 = {
        "id": "tool1",
        "source": "bioconda",
        "version": "1.0",
        "packageSpec": "tool=1.0",
        "environmentLock": {"adapter": "conda", "name": "env2"},
    }
    hash1 = tool_spec_hash(tool1)
    hash2 = tool_spec_hash(tool2)
    assert hash1 != hash2


def test_tool_spec_hash_without_environment_lock():
    tool = {
        "id": "tool1",
        "source": "bioconda",
        "version": "1.0",
        "packageSpec": "tool=1.0",
    }
    hash1 = tool_spec_hash(tool)
    assert len(hash1) == 64


def test_build_environment_lock_empty():
    tool = {"id": "tool1"}
    lock = build_environment_lock(tool)
    assert lock == {}


def test_build_environment_lock_conda():
    tool = {
        "id": "tool1",
        "environmentSpec": {
            "adapter": "conda",
            "name": "test-env",
            "channels": ["conda-forge"],
            "dependencies": ["python=3.11"],
        },
    }
    lock = build_environment_lock(tool)
    assert lock["adapter"] == "conda"
    assert lock["name"] == "test-env"
    assert lock["channels"] == ["conda-forge"]
    assert lock["dependencies"] == ["python=3.11"]


def test_build_environment_lock_apptainer():
    tool = {
        "id": "tool1",
        "environmentSpec": {
            "adapter": "apptainer",
            "image": "docker://ubuntu:22.04",
            "digest": "sha256:abc123",
        },
    }
    lock = build_environment_lock(tool)
    assert lock["adapter"] == "apptainer"
    assert lock["image"] == "docker://ubuntu:22.04"
    assert lock["digest"] == "sha256:abc123"


def test_build_environment_lock_native():
    tool = {
        "id": "tool1",
        "environmentSpec": {"adapter": "native"},
    }
    lock = build_environment_lock(tool)
    assert lock["adapter"] == "native"


def test_build_environment_lock_default_conda():
    tool = {
        "id": "tool1",
        "environmentSpec": {
            "name": "test-env",
            "dependencies": ["python"],
        },
    }
    lock = build_environment_lock(tool)
    assert lock["adapter"] == "conda"
    assert lock["name"] == "test-env"
