from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
import re
import secrets
import shlex
from typing import Any


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class RemoteRunnerBootstrapBundleMixin:
    _manager_error: type[Exception]

    def _deploy_service_runtime_bundle(
        self,
        *,
        ssh_service,
        artifact: Any,
        paths: Any,
    ) -> None:
        artifact_sha = self._require_local_service_runtime_artifact(artifact)
        remote_upload = f"{paths.bundle}.upload-{secrets.token_hex(16)}.tmp"
        self._run_checked(
            ssh_service,
            "mkdir -p "
            + " ".join(shlex.quote(path) for path in paths.remote_directories()),
            step="prepare remote runner directories",
            timeout=20,
        )
        try:
            ssh_service.upload(str(artifact.archive_path), remote_upload)
            self._run_checked(
                ssh_service,
                self._verify_and_publish_bundle_command(
                    remote_upload=remote_upload,
                    remote_bundle=paths.bundle,
                    expected_sha256=artifact_sha,
                ),
                step="verify and publish remote runner bundle",
                timeout=60,
            )
        except BaseException as error:
            try:
                self._cleanup_remote_bundle(
                    ssh_service,
                    remote_upload,
                    step="cleanup rejected remote runner bundle upload",
                )
            except BaseException as cleanup_error:
                raise BaseExceptionGroup(
                    "remote runner bundle upload and temporary cleanup both failed",
                    [error, cleanup_error],
                ) from None
            raise

        self._run_checked(
            ssh_service,
            "systemctl --user stop h2ometa-remote.service >/dev/null 2>&1 || true; "
            "pkill -f '[r]emote_runner.run' >/dev/null 2>&1 || true; "
            f"rm -f {shlex.quote(paths.runtime_state)}",
            step="clear previous remote runner service",
            timeout=20,
        )
        self._run_checked(
            ssh_service,
            "rm -rf {release} && mkdir -p {release} && tar -xzf {bundle} -C {release} && chmod 0755 {release}/*.sh".format(
                release=shlex.quote(paths.release),
                bundle=shlex.quote(paths.bundle),
            ),
            step="extract remote runner bundle",
            timeout=60,
        )
        self._write_remote_text_atomic(
            ssh_service,
            path=paths.artifact_sha,
            content=artifact_sha,
            step="write remote runner artifact marker",
            timeout=10,
        )
        self._cleanup_remote_bundle(
            ssh_service,
            paths.bundle,
            step="cleanup remote runner bundle",
        )

    @classmethod
    def _require_local_service_runtime_artifact(cls, artifact: Any) -> str:
        expected_sha256 = str(getattr(artifact, "sha256", "") or "")
        if _SHA256_PATTERN.fullmatch(expected_sha256) is None:
            raise cls._manager_error("remote runner artifact SHA-256 is invalid")

        try:
            archive_path = Path(getattr(artifact, "archive_path", ""))
            with archive_path.open("rb") as handle:
                actual_sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
        except (OSError, TypeError, ValueError) as exc:
            raise cls._manager_error(
                "remote runner artifact cannot be verified locally"
            ) from exc
        if not hmac.compare_digest(actual_sha256, expected_sha256):
            raise cls._manager_error("remote runner artifact local SHA-256 mismatch")
        return expected_sha256

    @staticmethod
    def _verify_and_publish_bundle_command(
        *,
        remote_upload: str,
        remote_bundle: str,
        expected_sha256: str,
    ) -> str:
        return (
            "test -s {upload} && "
            'actual="$(sha256sum {upload})" && '
            'actual="${{actual%% *}}" && '
            'test "$actual" = {expected} && '
            "mv -f {upload} {bundle}"
        ).format(
            upload=shlex.quote(remote_upload),
            bundle=shlex.quote(remote_bundle),
            expected=shlex.quote(expected_sha256),
        )
