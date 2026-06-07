from __future__ import annotations


def test_conda_dependency_parser_rejects_ranges_and_unsupported_explicit_channels() -> None:
    from apps.api.tool_candidate_dependencies import parse_conda_dependency

    assert parse_conda_dependency("fastqc >=0.12.1", channels=["bioconda"]) is None
    assert parse_conda_dependency("fastqc >0.12.1", channels=["bioconda"]) is None
    assert parse_conda_dependency("fastqc ~=0.12", channels=["bioconda"]) is None
    assert parse_conda_dependency("defaults::fastqc=0.12.1", channels=["bioconda"]) is None


def test_conda_dependency_parser_keeps_supported_explicit_channels() -> None:
    from apps.api.tool_candidate_dependencies import parse_conda_dependency

    dependency = parse_conda_dependency("conda-forge::pigz =2.8", channels=["bioconda"])

    assert dependency == {"source": "conda-forge", "name": "pigz", "version": "2.8"}
