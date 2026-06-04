from __future__ import annotations

import shlex
import time
from pathlib import Path, PurePosixPath
from typing import Any

from core.remote_runner.artifact import RemoteRunnerArtifactError, WorkflowRuntimeArtifact
from core.remote_runner.workflow_runtime_policy import (
    allow_remote_workflow_runtime_registration,
    workflow_runtime_artifact_required_message,
)


class RemoteRunnerWorkflowRuntimeMixin:
    _manager_error: type[Exception]

    def _resolve_workflow_artifact_for_bootstrap(
        self,
        *,
        ssh_service,
        version: str,
        platform: str,
        remote_dir: str,
        remote_bundle: str,
    ) -> WorkflowRuntimeArtifact:
        try:
            return self._workflow_artifact_provider.resolve(version=version, platform=platform)
        except RemoteRunnerArtifactError as exc:
            if not allow_remote_workflow_runtime_registration():
                raise self._manager_error(workflow_runtime_artifact_required_message()) from exc
            return self._resolve_remote_workflow_artifact(
                ssh_service=ssh_service,
                version=version,
                platform=platform,
                remote_dir=remote_dir,
                remote_bundle=remote_bundle,
                local_error=str(exc),
            )

    @classmethod
    def _resolve_remote_workflow_artifact(
        cls,
        *,
        ssh_service,
        version: str,
        platform: str,
        remote_dir: str,
        remote_bundle: str,
        local_error: str,
    ) -> WorkflowRuntimeArtifact:
        manifest = cls._read_remote_json(ssh_service, f"{remote_dir}/bootstrap_manifest.json", "remote workflow runtime manifest")
        if str(manifest.get("service") or "") != "h2ometa-workflow-runtime":
            raise cls._manager_error("remote workflow runtime manifest has unexpected service")
        if str(manifest.get("version") or "") != version:
            raise cls._manager_error("remote workflow runtime manifest version mismatch")
        if str(manifest.get("platform") or "") != platform:
            raise cls._manager_error("remote workflow runtime manifest platform mismatch")
        if str(manifest.get("provider") or "") != "conda-pack":
            raise cls._manager_error("remote workflow runtime manifest must declare conda-pack provider")
        packages = manifest.get("packages") if isinstance(manifest.get("packages"), dict) else {}
        if not str(packages.get("snakemake") or "").strip():
            raise cls._manager_error("remote workflow runtime manifest must declare snakemake package version")

        sha256 = cls._read_remote_workflow_artifact_sha(
            ssh_service=ssh_service,
            remote_dir=remote_dir,
            remote_bundle=remote_bundle,
        )
        if not sha256:
            raise cls._manager_error(
                "workflow runtime artifact unavailable locally and remote artifact checksum unavailable: "
                f"{local_error}"
            )

        entrypoints = manifest.get("entrypoints") if isinstance(manifest.get("entrypoints"), dict) else {}
        python_entrypoint = str(entrypoints.get("python") or "workflow-env/bin/python")
        snakemake_entrypoint = str(entrypoints.get("snakemake") or "workflow-env/bin/snakemake")
        conda_unpack_entrypoint = str(entrypoints.get("condaUnpack") or "workflow-env/bin/conda-unpack")
        conda_entrypoint = str(entrypoints.get("conda") or "workflow-env/bin/conda")
        for label, value in (
            ("python", python_entrypoint),
            ("snakemake", snakemake_entrypoint),
            ("condaUnpack", conda_unpack_entrypoint),
            ("conda", conda_entrypoint),
        ):
            if value.startswith("/") or ".." in Path(value).parts:
                raise cls._manager_error(f"remote workflow runtime manifest has invalid {label} entrypoint")

        return WorkflowRuntimeArtifact(
            version=version,
            platform=platform,
            archive_path=Path(""),
            sha256=sha256,
            manifest=manifest,
            snakemake_entrypoint=snakemake_entrypoint,
            conda_unpack_entrypoint=conda_unpack_entrypoint,
            python_entrypoint=python_entrypoint,
            conda_entrypoint=conda_entrypoint,
        )

    @staticmethod
    def _read_remote_workflow_artifact_sha(*, ssh_service, remote_dir: str, remote_bundle: str) -> str:
        exit_code, stdout, _stderr = ssh_service.run(f"cat {shlex.quote(f'{remote_dir}/artifact.sha256')}", timeout=10)
        if exit_code == 0 and stdout.strip():
            return stdout.strip()
        exit_code, stdout, _stderr = ssh_service.run(
            "test -f {bundle} && sha256sum {bundle}".format(bundle=shlex.quote(remote_bundle)),
            timeout=60,
        )
        if exit_code == 0 and stdout.strip():
            return stdout.strip().split(maxsplit=1)[0]
        return ""

    @classmethod
    def _verify_workflow_runtime_command(cls, ssh_service, cmd: str) -> tuple[int, str, str]:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return cls._run_checked(
                    ssh_service,
                    cmd,
                    step="verify workflow runtime snakemake",
                    timeout=30,
                )
            except cls._manager_error as exc:
                last_error = exc
                if attempt < 4:
                    time.sleep(1)
        if last_error is not None:
            raise last_error
        raise cls._manager_error("verify workflow runtime snakemake failed")

    @classmethod
    def _verify_workflow_runtime_for_reuse(
        cls,
        *,
        ssh_service,
        artifact: WorkflowRuntimeArtifact,
        remote_dir: str,
        remote_artifact_sha: str,
        remote_config: str,
    ) -> None:
        expected = cls._build_workflow_runtime_metadata(artifact=artifact, remote_dir=remote_dir)
        exit_code, stdout, stderr = ssh_service.run(f"cat {shlex.quote(remote_artifact_sha)}", timeout=10)
        if exit_code != 0:
            detail = stderr.strip() or stdout.strip() or "workflow runtime artifact marker missing"
            raise cls._manager_error(detail)
        if stdout.strip() != artifact.sha256:
            raise cls._manager_error("workflow runtime artifact sha mismatch")

        config = cls._read_remote_json(ssh_service, remote_config, "remote runner config")
        expected_config = {
            "managed_conda_command": str(expected.get("command") or ""),
            "managed_conda_root_prefix": str(expected.get("root_prefix") or ""),
            "workflow_runtime_provider": str(expected.get("provider") or ""),
            "workflow_runtime_source": str(expected.get("source") or ""),
            "workflow_runtime_version": str(expected.get("version") or ""),
            "snakemake_command": str(expected.get("snakemake_command") or ""),
            "snakemake_version": str(expected.get("snakemake_version") or ""),
        }
        for key, value in expected_config.items():
            if str(config.get(key) or "") != value:
                raise cls._manager_error(f"workflow runtime config mismatch: {key}")

        cls._verify_workflow_runtime_command(
            ssh_service,
            cls._workflow_runtime_command(
                python_command=str(expected["python"]),
                snakemake_command=str(expected["snakemake_command"]),
                conda_command=str(expected["command"]),
            ),
        )

    def _ensure_workflow_runtime(
        self,
        *,
        ssh_service,
        artifact: WorkflowRuntimeArtifact,
        remote_bundle: str,
        remote_dir: str,
        remote_artifact_sha: str,
        bootstrap_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        runtime = self._build_workflow_runtime_metadata(artifact=artifact, remote_dir=remote_dir)
        workflow_metadata = {"action": "reused", "path": remote_dir, "artifact_sha": artifact.sha256}
        exit_code, stdout, _stderr = ssh_service.run(f"cat {shlex.quote(remote_artifact_sha)}", timeout=10)
        reusable = exit_code == 0 and stdout.strip() == artifact.sha256
        runtime_verified = False
        if reusable:
            try:
                self._verify_workflow_runtime_command(
                    ssh_service,
                    self._workflow_runtime_command(
                        python_command=str(runtime["python"]),
                        snakemake_command=str(runtime["snakemake_command"]),
                        conda_command=str(runtime["command"]),
                    ),
                )
                runtime_verified = True
            except self._manager_error:
                reusable = False
                workflow_metadata["action"] = "reinstalled"
        if not reusable:
            if allow_remote_workflow_runtime_registration() and self._can_register_existing_workflow_runtime(ssh_service=ssh_service, runtime=runtime):
                workflow_metadata["action"] = "registered"
                runtime_verified = True
            else:
                if workflow_metadata["action"] != "reinstalled":
                    workflow_metadata["action"] = "installed"
                if not self._remote_file_has_sha256(
                    ssh_service=ssh_service,
                    path=remote_bundle,
                    sha256=artifact.sha256,
                ):
                    if not artifact.archive_path or not artifact.archive_path.exists():
                        raise self._manager_error(
                            "workflow runtime artifact unavailable locally and remote bundle is missing or has the wrong checksum"
                        )
                    ssh_service.upload(str(artifact.archive_path), remote_bundle)
                self._extract_workflow_runtime(
                    ssh_service=ssh_service,
                    remote_bundle=remote_bundle,
                    remote_dir=remote_dir,
                    runtime=runtime,
                )
        if not runtime_verified:
            self._verify_workflow_runtime_command(
                ssh_service,
                self._workflow_runtime_command(
                    python_command=str(runtime["python"]),
                    snakemake_command=str(runtime["snakemake_command"]),
                    conda_command=str(runtime["command"]),
                ),
            )
            runtime_verified = True
        if not reusable:
            self._write_remote_text_atomic(
                ssh_service,
                path=remote_artifact_sha,
                content=artifact.sha256,
                step="write workflow runtime artifact marker",
                timeout=10,
            )
            self._cleanup_remote_bundle(
                ssh_service,
                remote_bundle,
                step="cleanup workflow runtime bundle",
            )
        tooling = bootstrap_metadata.setdefault("tooling", {})
        tooling["workflow_runtime"] = runtime
        bootstrap_metadata["workflow_runtime"] = workflow_metadata
        return runtime

    @classmethod
    def _can_register_existing_workflow_runtime(cls, *, ssh_service, runtime: dict[str, Any]) -> bool:
        try:
            cls._verify_workflow_runtime_command(
                ssh_service,
                cls._workflow_runtime_command(
                    python_command=str(runtime["python"]),
                    snakemake_command=str(runtime["snakemake_command"]),
                    conda_command=str(runtime["command"]),
                ),
            )
            return True
        except cls._manager_error:
            return False

    @classmethod
    def _extract_workflow_runtime(
        cls,
        *,
        ssh_service,
        remote_bundle: str,
        remote_dir: str,
        runtime: dict[str, Any],
    ) -> None:
        cls._run_checked(
            ssh_service,
            "rm -rf {runtime_dir} && mkdir -p {runtime_dir} && tar -xzf {bundle} -C {runtime_dir}".format(
                runtime_dir=shlex.quote(remote_dir),
                bundle=shlex.quote(remote_bundle),
            ),
            step="extract workflow runtime artifact",
            timeout=180,
        )
        cls._run_checked(
            ssh_service,
            "if [ -x {conda_unpack} ] && [ ! -f {marker} ]; then {python} {conda_unpack}; touch {marker}; fi".format(
                conda_unpack=shlex.quote(str(runtime["conda_unpack"])),
                marker=shlex.quote(f"{remote_dir}/.h2ometa-conda-unpacked"),
                python=shlex.quote(str(runtime["python"])),
            ),
            step="relocate workflow runtime",
            timeout=120,
        )

    @staticmethod
    def _remote_file_has_sha256(*, ssh_service, path: str, sha256: str) -> bool:
        command = "test -f {path} && sha256sum {path}".format(path=shlex.quote(path))
        exit_code, stdout, _stderr = ssh_service.run(command, timeout=60)
        digest = stdout.strip().split(maxsplit=1)[0] if stdout.strip() else ""
        return exit_code == 0 and digest == sha256

    @staticmethod
    def _workflow_runtime_command(*, python_command: str, snakemake_command: str, conda_command: str) -> str:
        path_entries = [
            str(PurePosixPath(snakemake_command).parent),
            str(PurePosixPath(conda_command).parent),
        ]
        path_prefix = ":".join(shlex.quote(entry) for entry in dict.fromkeys(path_entries) if entry)
        return "PATH={path_prefix}:$PATH {python} -c 'import snakemake' && PATH={path_prefix}:$PATH {snakemake} --version".format(
            path_prefix=path_prefix,
            python=shlex.quote(python_command),
            snakemake=shlex.quote(snakemake_command),
        )
