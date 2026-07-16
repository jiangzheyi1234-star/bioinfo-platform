from __future__ import annotations

from copy import deepcopy

import pytest

from core.remote_runner.environment import RemoteRunnerEnvironmentMixin
from tests.helpers.remote_runner_control_plane import (
    _remote_runner_manifest,
    _remote_runner_protocol_config,
)


class _Environment(RemoteRunnerEnvironmentMixin):
    _manager_error = RuntimeError

    remote_config: dict[str, object] = {}

    @classmethod
    def _read_remote_json(cls, _ssh_service, _path: str, _context: str):
        return dict(cls.remote_config)


def test_remote_manifest_requires_exact_current_runner_protocol() -> None:
    manifest = _remote_runner_manifest(version="protocol-test")

    _Environment._verify_remote_manifest(
        manifest,
        version="protocol-test",
        platform="linux-64",
    )


def test_remote_manifest_rejects_legacy_runner_without_protocol() -> None:
    manifest = _remote_runner_manifest(version="protocol-test")
    manifest.pop("runnerProtocol")

    with pytest.raises(RuntimeError, match="descriptor must be an object"):
        _Environment._verify_remote_manifest(
            manifest,
            version="protocol-test",
            platform="linux-64",
        )


def test_reuse_manifest_rejects_changed_descriptor_with_old_fingerprint() -> None:
    manifest = deepcopy(_remote_runner_manifest(version="protocol-test"))
    manifest["runnerProtocol"]["coverage"]["automaticRecoveryEnabled"] = True

    with pytest.raises(RuntimeError, match="automaticRecoveryEnabled"):
        _Environment._verify_remote_manifest_for_reuse(
            manifest,
            version="protocol-test",
            platform="linux-64",
        )


def test_reuse_protocol_config_matches_manifest_and_release() -> None:
    release = "/runner/releases/protocol-test"
    manifest = _remote_runner_manifest(version="protocol-test")
    _Environment.remote_config = _remote_runner_protocol_config(
        version="protocol-test",
        release=release,
    )

    _Environment._verify_remote_protocol_config_for_reuse(
        ssh_service=object(),
        remote_config="/runner/shared/config/runner.json",
        remote_release=release,
        manifest=manifest,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("service_name", "wrong-service"),
        ("version", "other-version"),
        ("release_dir", "/runner/releases/other/remote_runner"),
        ("runner_python", "/runner/releases/other/runtime/bin/python"),
        ("runner_protocol_version", "runner-protocol.v0"),
        ("runner_protocol_fingerprint", "sha256:" + "0" * 64),
    ],
)
def test_reuse_protocol_config_rejects_four_way_drift(field: str, value: str) -> None:
    release = "/runner/releases/protocol-test"
    manifest = _remote_runner_manifest(version="protocol-test")
    _Environment.remote_config = {
        **_remote_runner_protocol_config(
            version="protocol-test",
            release=release,
        ),
        field: value,
    }

    with pytest.raises(RuntimeError, match=field):
        _Environment._verify_remote_protocol_config_for_reuse(
            ssh_service=object(),
            remote_config="/runner/shared/config/runner.json",
            remote_release=release,
            manifest=manifest,
        )
