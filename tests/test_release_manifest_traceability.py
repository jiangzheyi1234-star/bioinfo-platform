from __future__ import annotations

from scripts import check_release_manifest_traceability as traceability


def _spec(source_commit: str = "a" * 40) -> dict:
    return {
        "schema_version": 1,
        "artifacts": {
            "remote_runner": {
                "name": "h2ometa-remote-runner",
                "default_platform": "linux-64",
                "sha256": {"linux-64": "b" * 64},
                "size_bytes": {"linux-64": 123},
                "lock_sha256": {"linux-64": "c" * 64},
                "download_urls": {
                    "linux-64": "https://api.github.com/repos/owner/repo/releases/assets/1",
                },
                "sbom_urls": {
                    "linux-64": "https://api.github.com/repos/owner/repo/releases/assets/2",
                },
                "provenance_urls": {
                    "linux-64": "https://api.github.com/repos/owner/repo/releases/assets/3",
                },
                "attestation_urls": {
                    "linux-64": "https://api.github.com/repos/owner/repo/releases/assets/4",
                },
                "signature_urls": {
                    "linux-64": "https://api.github.com/repos/owner/repo/releases/assets/4",
                },
                "builder_ids": {
                    "linux-64": "owner/repo/.github/workflows/release-remote-runner-artifacts.yml@refs/tags/h2ometa-runtime-v0.1.2",
                },
                "source_refs": {"linux-64": source_commit},
                "source_commits": {"linux-64": source_commit},
            }
        },
    }


def test_traceability_accepts_complete_manifest(monkeypatch) -> None:
    source_commit = "a" * 40

    def fake_git_commit(ref: str) -> str:
        assert ref in {source_commit, "h2ometa-runtime-v0.1.2"}
        return source_commit

    monkeypatch.setattr(traceability, "git_commit", fake_git_commit)

    errors = traceability.check_manifest(_spec(source_commit), release_tag="h2ometa-runtime-v0.1.2")

    assert errors == []


def test_traceability_rejects_missing_source_commit(monkeypatch) -> None:
    monkeypatch.setattr(traceability, "git_commit", lambda ref: (_ for _ in ()).throw(RuntimeError("missing")))

    errors = traceability.check_manifest(_spec("d" * 40), release_tag="")

    assert any("source commit is not present" in error for error in errors)


def test_traceability_rejects_tag_that_points_elsewhere(monkeypatch) -> None:
    source_commit = "a" * 40

    def fake_git_commit(ref: str) -> str:
        if ref == source_commit:
            return source_commit
        if ref == "h2ometa-runtime-v0.1.2":
            return "e" * 40
        raise AssertionError(ref)

    monkeypatch.setattr(traceability, "git_commit", fake_git_commit)

    errors = traceability.check_manifest(_spec(source_commit), release_tag="h2ometa-runtime-v0.1.2")

    assert any("points at" in error for error in errors)


def test_traceability_rejects_non_release_asset_url(monkeypatch) -> None:
    monkeypatch.setattr(traceability, "git_commit", lambda ref: "a" * 40)
    manifest = _spec()
    manifest["artifacts"]["remote_runner"]["download_urls"]["linux-64"] = "https://example.com/artifact.tar.gz"

    errors = traceability.check_manifest(manifest, release_tag="")

    assert any("invalid download_urls" in error for error in errors)


def test_traceability_rejects_unexpected_tag_name(monkeypatch) -> None:
    monkeypatch.setattr(traceability, "git_commit", lambda ref: "a" * 40)

    errors = traceability.check_manifest(_spec(), release_tag="v0.1.2")

    assert any("release tag must match" in error for error in errors)
