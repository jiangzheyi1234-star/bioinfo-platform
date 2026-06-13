from __future__ import annotations

from apps.remote_runner.env_adapters import (
    ApptainerAdapter,
    CondaAdapter,
    NativeAdapter,
    build_adapter,
    list_adapters,
)
from apps.remote_runner.env_adapters.base import EnvironmentLock


def test_list_adapters():
    adapters = list_adapters()
    assert "native" in adapters
    assert "conda" in adapters
    assert "apptainer" in adapters


def test_build_adapter_native():
    adapter = build_adapter("native")
    assert adapter.name == "native"


def test_build_adapter_conda():
    adapter = build_adapter("conda", conda_command="/usr/bin/conda")
    assert adapter.name == "conda"


def test_build_adapter_apptainer():
    adapter = build_adapter("apptainer")
    assert adapter.name == "apptainer"


def test_build_adapter_unknown():
    try:
        build_adapter("docker")
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "UNKNOWN_ENVIRONMENT_ADAPTER" in str(exc)


def test_native_adapter_inspect():
    adapter = NativeAdapter()
    inspection = adapter.inspect()
    assert inspection.ok
    assert inspection.adapter == "native"


def test_native_adapter_prepare():
    adapter = NativeAdapter()
    lock = adapter.prepare(work_dir="/tmp", environment_spec={})
    assert lock.adapter == "native"


def test_native_adapter_build_command():
    adapter = NativeAdapter()
    cmd = adapter.build_command(["echo", "hello"], work_dir="/tmp")
    assert cmd == ["echo", "hello"]


def test_native_adapter_build_environment():
    adapter = NativeAdapter()
    env = adapter.build_environment(work_dir="/tmp")
    assert "PATH" in env


def test_conda_adapter_inspect_not_configured():
    adapter = CondaAdapter()
    inspection = adapter.inspect()
    assert not inspection.ok
    assert "not configured" in inspection.message


def test_conda_adapter_inspect_missing():
    adapter = CondaAdapter(conda_command="/nonexistent/conda")
    inspection = adapter.inspect()
    assert not inspection.ok
    assert "does not exist" in inspection.message


def test_conda_adapter_prepare_empty():
    adapter = CondaAdapter()
    lock = adapter.prepare(work_dir="/tmp", environment_spec={})
    assert lock.adapter == "conda"


def test_conda_adapter_prepare_with_spec():
    adapter = CondaAdapter()
    lock = adapter.prepare(
        work_dir="/tmp",
        environment_spec={
            "name": "test-env",
            "channels": ["conda-forge"],
            "dependencies": ["python=3.11"],
        },
    )
    assert lock.adapter == "conda"
    assert lock.metadata["name"] == "test-env"
    assert lock.metadata["channels"] == ["conda-forge"]


def test_conda_adapter_build_environment():
    adapter = CondaAdapter(conda_command="/usr/bin/conda", conda_prefix="/opt/conda")
    env = adapter.build_environment(work_dir="/tmp")
    assert "PATH" in env
    assert env.get("CONDA_EXE") == "/usr/bin/conda"
    assert env.get("MAMBA_ROOT_PREFIX") == "/opt/conda"


def test_apptainer_adapter_inspect_not_available():
    adapter = ApptainerAdapter(apptainer_command="nonexistent-apptainer")
    inspection = adapter.inspect()
    assert not inspection.ok
    assert not inspection.supported


def test_apptainer_adapter_prepare_empty():
    adapter = ApptainerAdapter()
    lock = adapter.prepare(work_dir="/tmp", environment_spec={})
    assert lock.adapter == "apptainer"


def test_apptainer_adapter_prepare_with_image():
    adapter = ApptainerAdapter()
    lock = adapter.prepare(
        work_dir="/tmp",
        environment_spec={
            "image": "docker://ubuntu:22.04",
            "digest": "sha256:abc123",
            "binds": ["/data:/data"],
            "nv": True,
        },
    )
    assert lock.adapter == "apptainer"
    assert lock.digest == "sha256:abc123"
    assert lock.metadata["image"] == "docker://ubuntu:22.04"
    assert lock.metadata["nv"] is True


def test_apptainer_adapter_build_command_no_image():
    adapter = ApptainerAdapter()
    cmd = adapter.build_command(["echo", "hello"], work_dir="/tmp")
    assert cmd == ["echo", "hello"]


def test_apptainer_adapter_build_command_with_lock():
    adapter = ApptainerAdapter(apptainer_command="apptainer")
    lock = EnvironmentLock(
        adapter="apptainer",
        version="1.0",
        digest="sha256:abc",
        metadata={
            "image": "docker://ubuntu:22.04",
            "binds": ["/data:/data"],
            "nv": True,
            "writable": True,
        },
    )
    cmd = adapter.build_command(["echo", "hello"], work_dir="/tmp", environment_lock=lock)
    assert cmd == [
        "apptainer",
        "exec",
        "--nv",
        "--writable",
        "--pwd",
        "/tmp",
        "--bind",
        "/data:/data",
        "--bind",
        "/tmp:/tmp",
        "docker://ubuntu:22.04",
        "echo",
        "hello",
    ]


def test_environment_lock_to_dict():
    lock = EnvironmentLock(
        adapter="conda",
        version="23.0",
        digest="abc123",
        metadata={"name": "test"},
    )
    d = lock.to_dict()
    assert d["adapter"] == "conda"
    assert d["version"] == "23.0"
    assert d["digest"] == "abc123"
    assert d["metadata"]["name"] == "test"
