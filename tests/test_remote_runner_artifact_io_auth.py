from __future__ import annotations

from pathlib import Path

import pytest

from core.remote_runner import artifact_io


def test_github_cli_token_uses_h2ometa_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = []

    def fake_which(name: str) -> str:
        assert name == "gh"
        return "gh"

    def fake_run(args, *, capture_output, check, env, text, timeout):
        calls.append((args, env))

        class Result:
            returncode = 0
            stdout = "gh-token\n"

        return Result()

    artifact_io.github_cli_auth_token.cache_clear()
    monkeypatch.delenv("GH_CONFIG_DIR", raising=False)
    monkeypatch.setenv("H2OMETA_GH_CONFIG_DIR", str(tmp_path / "gh-cli"))
    monkeypatch.setattr(artifact_io.shutil, "which", fake_which)
    monkeypatch.setattr(artifact_io.subprocess, "run", fake_run)

    assert artifact_io.github_cli_auth_token() == "gh-token"
    assert calls[0][0] == ["gh", "auth", "token", "--hostname", "github.com"]
    assert calls[0][1]["GH_CONFIG_DIR"] == str(tmp_path / "gh-cli")
    artifact_io.github_cli_auth_token.cache_clear()


def test_download_headers_accepts_personal_access_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_io.github_cli_auth_token.cache_clear()
    monkeypatch.delenv("H2OMETA_RELEASE_DOWNLOAD_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", "pat-token")

    assert artifact_io.download_headers()["Authorization"] == "Bearer pat-token"
    artifact_io.github_cli_auth_token.cache_clear()
