from core.remote.server_capabilities import ServerCapabilities


def build_caps(java_version: str, has_java: bool = True) -> ServerCapabilities:
    return ServerCapabilities(
        arch="x86_64",
        has_bash=True,
        has_curl=True,
        has_wget=False,
        has_screen=True,
        has_sha256sum=True,
        has_java=has_java,
        java_version=java_version,
        has_nextflow=True,
        nextflow_version="24.10.0",
        has_docker=True,
        has_podman=False,
        has_apptainer=False,
        has_micromamba=False,
        has_conda=False,
        has_sbatch=False,
        free_disk_gb=100.0,
        home_writable=True,
    )


def test_java_11_is_not_supported_for_nextflow() -> None:
    caps = build_caps('openjdk version "11.0.30" 2026-01-20')
    assert caps.java_major == 11
    assert caps.has_supported_java is False
    assert "Java 17-24" in " ".join(caps.runtime_failures())


def test_java_17_is_supported_for_nextflow() -> None:
    caps = build_caps('openjdk version "17.0.14" 2025-10-15')
    assert caps.java_major == 17
    assert caps.has_supported_java is True
