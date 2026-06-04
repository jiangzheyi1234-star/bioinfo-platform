from __future__ import annotations

import shlex
from typing import Any


class RemoteRunnerBootstrapBundleMixin:
    def _deploy_service_runtime_bundle(
        self,
        *,
        ssh_service,
        artifact: Any,
        paths: Any,
    ) -> None:
        self._run_checked(
            ssh_service,
            "mkdir -p " + " ".join(shlex.quote(path) for path in paths.remote_directories()),
            step="prepare remote runner directories",
            timeout=20,
        )
        self._run_checked(
            ssh_service,
            "systemctl --user stop h2ometa-remote.service >/dev/null 2>&1 || true; "
            "pkill -f '[r]emote_runner.run' >/dev/null 2>&1 || true; "
            f"rm -f {shlex.quote(paths.runtime_state)}",
            step="clear previous remote runner service",
            timeout=20,
        )
        ssh_service.upload(str(artifact.archive_path), paths.bundle)
        self._run_checked(
            ssh_service,
            "rm -rf {release} && mkdir -p {release} && tar -xzf {bundle} -C {release} && chmod 0755 {release}/*.sh".format(
                release=shlex.quote(paths.release),
                bundle=shlex.quote(paths.bundle),
            ),
            step="extract remote runner bundle",
            timeout=60,
        )
        artifact_sha = str(getattr(artifact, "sha256", "") or "")
        if artifact_sha:
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
