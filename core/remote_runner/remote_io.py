from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any


class RemoteRunnerRemoteIoMixin:
    @classmethod
    def _read_remote_json_if_exists(cls, ssh_service, path: str, label: str) -> dict[str, Any] | None:
        exit_code, stdout, _stderr = ssh_service.run(f"cat {shlex.quote(path)}", timeout=10)
        if exit_code != 0:
            return None
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise cls._manager_error(f"{label} is invalid JSON") from exc
        if not isinstance(payload, dict):
            raise cls._manager_error(f"{label} is not an object")
        return payload

    @classmethod
    def _switch_current_release(cls, *, ssh_service, target: str, link_path: str) -> None:
        cls._run_checked(
            ssh_service,
            cls._atomic_symlink_command(target=target, link_path=link_path),
            step="switch current release",
            timeout=15,
        )

    @classmethod
    def _write_remote_text_atomic(
        cls,
        ssh_service,
        *,
        path: str,
        content: str,
        step: str,
        timeout: int,
    ) -> None:
        tmp_path = f"{path}.tmp"
        quoted_content = shlex.quote(content)
        quoted_tmp = shlex.quote(tmp_path)
        quoted_path = shlex.quote(path)
        cls._run_checked(
            ssh_service,
            "printf %s {content} > {tmp} && test -s {tmp} && mv -f {tmp} {path}".format(
                content=quoted_content,
                tmp=quoted_tmp,
                path=quoted_path,
            ),
            step=step,
            timeout=timeout,
        )

    @classmethod
    def _upload_remote_file_atomic(
        cls,
        ssh_service,
        *,
        local_path: Path,
        remote_path: str,
        step: str,
        timeout: int,
    ) -> None:
        tmp_path = f"{remote_path}.tmp"
        ssh_service.upload(str(local_path), tmp_path)
        cls._run_checked(
            ssh_service,
            "test -s {tmp} && mv -f {tmp} {path}".format(
                tmp=shlex.quote(tmp_path),
                path=shlex.quote(remote_path),
            ),
            step=step,
            timeout=timeout,
        )

    @staticmethod
    def _atomic_symlink_command(*, target: str, link_path: str) -> str:
        tmp_link = f"{link_path}.tmp"
        return (
            "rm -f {tmp} && "
            "ln -sfn {target} {tmp} && "
            "test -L {tmp} && "
            "mv -Tf {tmp} {link}"
        ).format(
            target=shlex.quote(target),
            tmp=shlex.quote(tmp_link),
            link=shlex.quote(link_path),
        )

    @classmethod
    def _cleanup_remote_bundle(cls, ssh_service, path: str, *, step: str) -> None:
        cls._run_checked(
            ssh_service,
            f"rm -f {shlex.quote(path)}",
            step=step,
            timeout=10,
        )

    @classmethod
    def _read_remote_json(cls, ssh_service, path: str, label: str) -> dict[str, Any]:
        exit_code, stdout, stderr = ssh_service.run(f"cat {shlex.quote(path)}", timeout=10)
        if exit_code != 0:
            detail = stderr.strip() or stdout.strip() or f"{label} not readable"
            raise cls._manager_error(detail)
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise cls._manager_error(f"{label} is invalid JSON") from exc
        if not isinstance(payload, dict):
            raise cls._manager_error(f"{label} is not an object")
        return payload

    @classmethod
    def _run_checked(cls, ssh_service, cmd: str, *, step: str, timeout: int) -> tuple[int, str, str]:
        exit_code, stdout, stderr = ssh_service.run(cmd, timeout=timeout)
        if exit_code != 0:
            detail = stderr.strip() or stdout.strip() or f"{step} failed"
            raise cls._manager_error(f"{step}: {detail}")
        return exit_code, stdout, stderr

    @staticmethod
    def _manager_error(message: str) -> RuntimeError:
        from core.remote_runner.manager import RemoteRunnerManagerError

        return RemoteRunnerManagerError(message)
