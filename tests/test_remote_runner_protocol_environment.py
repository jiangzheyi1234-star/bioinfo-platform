from __future__ import annotations

from copy import deepcopy

import pytest

from core.remote_runner.environment import RemoteRunnerEnvironmentMixin
from tests.helpers.remote_runner_control_plane import _remote_runner_manifest


class _Environment(RemoteRunnerEnvironmentMixin):
    _manager_error = RuntimeError


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
