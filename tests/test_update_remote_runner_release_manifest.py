from __future__ import annotations

import pytest

from scripts import update_remote_runner_release_manifest as updater


def _manifest() -> dict:
    return {
        "schema_version": 1,
        "relative_search_roots": ["resources/remote-runner"],
        "artifacts": {
            "remote_runner": {
                "name": "h2ometa-remote-runner",
                "service": "h2ometa-remote",
                "version": "0.1.1-control-plane",
                "default_platform": "linux-64",
                "bundle_env_var": "H2OMETA_REMOTE_RUNNER_BUNDLE",
                "search_root_env_vars": ["H2OMETA_REMOTE_RUNNER_DIR"],
            }
        },
    }


def _metadata() -> dict:
    return {
        "schemaVersion": "h2ometa-release-artifacts-ci.v1",
        "builder": {
            "type": "github-actions",
            "id": "owner/repo/.github/workflows/release.yml@refs/tags/v0.1.1",
            "runUrl": "https://github.com/owner/repo/actions/runs/123",
        },
        "sourceRef": "refs/tags/v0.1.1",
        "sourceCommit": "a" * 40,
        "artifacts": [
            {
                "artifactKey": "remote_runner",
                "version": "0.1.1-control-plane",
                "platform": "linux-64",
                "path": "dist/remote-runner/runner.tar.gz",
                "sha256": "b" * 64,
                "sizeBytes": 123,
                "lock": {"sha256": "c" * 64},
                "sbom": {"path": "dist/remote-runner/runner.tar.gz.spdx.json", "sha256": "d" * 64},
                "sourceRef": "refs/tags/v0.1.1",
                "sourceCommit": "a" * 40,
            }
        ],
    }


def _published_assets() -> dict:
    return {
        "schemaVersion": "h2ometa-release-published-assets.v1",
        "repository": "owner/repo",
        "releaseTag": "v0.1.1",
        "assets": {
            "runner.tar.gz": {
                "apiUrl": "https://api.github.com/repos/owner/repo/releases/assets/1",
                "digest": "sha256:" + "b" * 64,
                "size": 123,
            },
            "runner.tar.gz.spdx.json": {
                "apiUrl": "https://api.github.com/repos/owner/repo/releases/assets/2",
                "digest": "sha256:" + "d" * 64,
                "size": 456,
            },
            "release-provenance.intoto.json": {
                "apiUrl": "https://api.github.com/repos/owner/repo/releases/assets/3",
                "digest": "sha256:" + "e" * 64,
                "size": 789,
            },
            "h2ometa-remote-runner-sbom.intoto.json": {
                "apiUrl": "https://api.github.com/repos/owner/repo/releases/assets/4",
                "digest": "sha256:" + "f" * 64,
                "size": 321,
            },
        },
    }


def _attestations() -> dict:
    return {
        "schemaVersion": "h2ometa-release-attestations.v1",
        "provenance": {
            "attestationId": "e" * 64,
            "attestationUrl": "pending-release-asset:release-provenance.intoto.json",
            "bundleSha256": "e" * 64,
        },
        "sbom": {
            "remote_runner": {
                "attestationId": "f" * 64,
                "attestationUrl": "pending-release-asset:h2ometa-remote-runner-sbom.intoto.json",
                "bundleSha256": "f" * 64,
            }
        },
    }


def _direct_attestations() -> dict:
    return {
        "schemaVersion": "h2ometa-release-attestations.v1",
        "provenance": {"attestationUrl": "https://github.com/owner/repo/attestations/provenance"},
        "sbom": {
            "remote_runner": {
                "attestationUrl": "https://github.com/owner/repo/attestations/remote-runner-sbom"
            }
        },
    }


def test_update_manifest_writes_release_metadata_and_supply_chain_fields() -> None:
    updated = updater.update_manifest(
        _manifest(),
        metadata=_metadata(),
        attestations=_attestations(),
        download_urls={("remote_runner", "linux-64"): "https://api.github.com/repos/owner/repo/releases/assets/1"},
        sbom_urls={
            ("remote_runner", "linux-64"): "https://api.github.com/repos/owner/repo/releases/assets/2"
        },
        published_assets=_published_assets(),
    )

    spec = updated["artifacts"]["remote_runner"]
    assert spec["sha256"]["linux-64"] == "b" * 64
    assert spec["size_bytes"]["linux-64"] == 123
    assert spec["lock_sha256"]["linux-64"] == "c" * 64
    assert spec["download_urls"]["linux-64"].endswith("/1")
    assert spec["sbom_urls"]["linux-64"].endswith("/2")
    assert spec["provenance_urls"]["linux-64"].endswith("/3")
    assert spec["attestation_urls"]["linux-64"].endswith("/4")
    assert spec["signature_urls"]["linux-64"].endswith("/4")
    assert spec["builder_ids"]["linux-64"].endswith("@refs/tags/v0.1.1")
    assert spec["source_refs"]["linux-64"] == "refs/tags/v0.1.1"
    assert spec["source_commits"]["linux-64"] == "a" * 40


def test_update_manifest_can_use_published_release_asset_map() -> None:
    download_urls, sbom_urls = updater.merge_published_asset_urls(
        metadata=_metadata(),
        published_assets=_published_assets(),
        download_urls={},
        sbom_urls={},
    )

    updated = updater.update_manifest(
        _manifest(),
        metadata=_metadata(),
        attestations=_attestations(),
        download_urls=download_urls,
        sbom_urls=sbom_urls,
        published_assets=_published_assets(),
    )

    spec = updated["artifacts"]["remote_runner"]
    assert spec["download_urls"]["linux-64"].endswith("/1")
    assert spec["sbom_urls"]["linux-64"].endswith("/2")
    assert spec["sha256"]["linux-64"] == "b" * 64
    assert spec["size_bytes"]["linux-64"] == 123
    assert spec["provenance_urls"]["linux-64"].endswith("/3")
    assert spec["attestation_urls"]["linux-64"].endswith("/4")


def test_update_manifest_resolves_pending_release_asset_attestations() -> None:
    download_urls, sbom_urls = updater.merge_published_asset_urls(
        metadata=_metadata(),
        published_assets=_published_assets(),
        download_urls={},
        sbom_urls={},
    )

    updated = updater.update_manifest(
        _manifest(),
        metadata=_metadata(),
        attestations=_attestations(),
        download_urls=download_urls,
        sbom_urls=sbom_urls,
        published_assets=_published_assets(),
    )

    spec = updated["artifacts"]["remote_runner"]
    assert spec["provenance_urls"]["linux-64"].endswith("/3")
    assert spec["attestation_urls"]["linux-64"].endswith("/4")
    assert spec["signature_urls"]["linux-64"].endswith("/4")


def test_update_manifest_preserves_direct_attestation_urls() -> None:
    updated = updater.update_manifest(
        _manifest(),
        metadata=_metadata(),
        attestations=_direct_attestations(),
        download_urls={("remote_runner", "linux-64"): "https://api.github.com/repos/owner/repo/releases/assets/1"},
        sbom_urls={
            ("remote_runner", "linux-64"): "https://api.github.com/repos/owner/repo/releases/assets/2"
        },
    )

    spec = updated["artifacts"]["remote_runner"]
    assert spec["provenance_urls"]["linux-64"].endswith("/provenance")
    assert spec["attestation_urls"]["linux-64"].endswith("/remote-runner-sbom")
    assert spec["signature_urls"]["linux-64"].endswith("/remote-runner-sbom")


def test_update_manifest_rejects_published_asset_digest_mismatch() -> None:
    published = _published_assets()
    published["assets"]["runner.tar.gz"]["digest"] = "sha256:" + "0" * 64

    with pytest.raises(SystemExit, match="published artifact sha256 mismatch"):
        updater.merge_published_asset_urls(
            metadata=_metadata(),
            published_assets=published,
            download_urls={},
            sbom_urls={},
        )


def test_update_manifest_rejects_published_asset_size_mismatch() -> None:
    published = _published_assets()
    published["assets"]["runner.tar.gz"]["size"] = 999

    with pytest.raises(SystemExit, match="published artifact size mismatch"):
        updater.merge_published_asset_urls(
            metadata=_metadata(),
            published_assets=published,
            download_urls={},
            sbom_urls={},
        )


def test_update_manifest_requires_download_url() -> None:
    with pytest.raises(SystemExit, match="missing download URL"):
        updater.update_manifest(
            _manifest(),
            metadata=_metadata(),
            attestations=_attestations(),
            download_urls={},
            sbom_urls={
                ("remote_runner", "linux-64"): "https://api.github.com/repos/owner/repo/releases/assets/2"
            },
            published_assets=_published_assets(),
        )


def test_update_manifest_requires_published_sbom_url() -> None:
    with pytest.raises(SystemExit, match="missing SBOM URL"):
        updater.update_manifest(
            _manifest(),
            metadata=_metadata(),
            attestations=_attestations(),
            download_urls={("remote_runner", "linux-64"): "https://api.github.com/repos/owner/repo/releases/assets/1"},
            sbom_urls={},
            published_assets=_published_assets(),
        )


def test_update_manifest_requires_attestation_urls() -> None:
    with pytest.raises(SystemExit, match="provenance attestationUrl"):
        updater.update_manifest(
            _manifest(),
            metadata=_metadata(),
            attestations={"schemaVersion": "h2ometa-release-attestations.v1"},
            download_urls={("remote_runner", "linux-64"): "https://api.github.com/repos/owner/repo/releases/assets/1"},
            sbom_urls={
                ("remote_runner", "linux-64"): "https://api.github.com/repos/owner/repo/releases/assets/2"
            },
        )
