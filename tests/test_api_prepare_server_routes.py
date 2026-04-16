from __future__ import annotations

import asyncio

import httpx

from apps.api import main as api_main


class _RuntimeFactory:
    def __init__(self, runtime: object) -> None:
        self.runtime = runtime

    def __call__(self) -> object:
        return self.runtime

    def cache_clear(self) -> None:  # pragma: no cover - startup/shutdown compatibility
        return None


class _FakeRuntime:
    def __init__(self) -> None:
        self.install_calls: list[dict[str, str]] = []

    def get_ssh_preflight(self) -> dict[str, object]:
        return {
            "ok": True,
            "recommended_profile": "personal_docker",
            "recommended_profile_details": {"profile_kind": "personal_docker"},
            "supported_profile_kinds": ["personal_docker"],
            "runtime_capabilities": {
                "java": {"available": True, "usable": True, "version": "17.0.9", "path": "/usr/bin/java"},
                "nextflow": {"available": True, "usable": True, "version": "25.04.0", "path": "/usr/local/bin/nextflow", "message": "已检测到 Nextflow，可直接使用"},
                "docker": {"available": True, "usable": True},
                "podman": {"available": False, "usable": False},
                "apptainer": {"available": False, "usable": False},
                "micromamba": {"available": False, "usable": False},
                "conda": {"available": False, "usable": False},
            },
            "checks": [
                {"key": "java", "label": "Java 17+", "status": "ok", "value": "17.0.9", "message": "已检测到 Java，可用于运行 Nextflow"},
                {"key": "nextflow", "label": "Nextflow", "status": "ok", "value": "25.04.0", "message": "已检测到 Nextflow"},
                {"key": "docker", "label": "Docker", "status": "ok", "value": "usable", "message": "已检测到 Docker，可优先使用容器模式"},
                {"key": "home_writable", "label": "HOME 可写", "status": "ok", "value": "writable", "message": "HOME 目录可写"},
            ],
            "failures": [],
            "warnings": [],
        }

    def get_remote_env_status(self) -> dict[str, object]:
        return {
            "conda_runtime": {
                "installed": False,
                "status": "not_installed",
                "version": "",
                "conda_executable": "",
                "message": "未检测到 Conda Runtime",
            },
            "tool_envs": [],
            "summary": {"total": 0, "installed": 0, "missing": 0, "env_paths": []},
        }

    def install_remote_env(self, *, target: str, tool_id: str = "", profile_kind: str = "") -> dict[str, str]:
        self.install_calls.append({"target": target, "tool_id": tool_id, "profile_kind": profile_kind})
        return {
            "target": target,
            "profile_kind": profile_kind,
            "job_id": "job_runtime",
            "task_dir": "/tmp/job_runtime",
            "message": f"submitted {target}",
        }

    def get_remote_env_install_status(self, *, job_id: str) -> dict[str, object]:
        return {
            "job_id": job_id,
            "status": "done",
            "done": True,
            "ok": True,
            "message": "bootstrap complete",
            "log_text": "done",
        }


class _FakeRuntimeMissingJava(_FakeRuntime):
    def get_ssh_preflight(self) -> dict[str, object]:
        return {
            "ok": False,
            "recommended_profile": "personal_docker",
            "recommended_profile_details": {"profile_kind": "personal_docker"},
            "supported_profile_kinds": ["personal_docker"],
            "runtime_capabilities": {
                "java": {"available": False, "usable": False, "supported": False, "version": "", "path": "", "message": "未检测到 Java，无法运行 Nextflow"},
                "nextflow": {"available": True, "usable": True, "version": "24.10.0", "path": "/home/zyserver/bin/nextflow", "message": "已检测到 Nextflow，可直接使用"},
                "docker": {"available": True, "usable": True},
                "podman": {"available": False, "usable": False},
                "apptainer": {"available": False, "usable": False},
                "micromamba": {"available": False, "usable": False},
                "conda": {"available": False, "usable": False},
            },
            "checks": [
                {"key": "java", "label": "Java 17+", "status": "fail", "value": "missing", "message": "未检测到 Java，无法运行 Nextflow"},
                {"key": "nextflow", "label": "Nextflow", "status": "ok", "value": "24.10.0", "message": "已检测到 Nextflow，可直接使用"},
                {"key": "docker", "label": "Docker", "status": "ok", "value": "usable", "message": "已检测到 Docker，可优先使用容器模式"},
            ],
            "failures": ["远端缺少 Java，无法运行 Nextflow"],
            "warnings": [],
        }


def test_prepare_server_routes_expose_expected_shapes(monkeypatch) -> None:
    runtime = _FakeRuntime()
    monkeypatch.setattr(api_main, "get_runtime_service", _RuntimeFactory(runtime))

    async def exercise_routes() -> None:
        transport = httpx.ASGITransport(app=api_main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            preflight = await client.post("/api/v1/ssh/preflight")
            assert preflight.status_code == 200
            preflight_item = preflight.json()["item"]
            assert preflight_item["recommended_profile"] == "personal_docker"
            assert preflight_item["runtime_capabilities"]["java"]["usable"] is True
            assert preflight_item["checks"][0]["key"] == "java"

            env_status = await client.get("/api/v1/ssh/env/status")
            assert env_status.status_code == 200
            assert env_status.json()["item"]["conda_runtime"]["installed"] is False
            assert preflight_item["runtime_capabilities"]["nextflow"]["path"] == "/usr/local/bin/nextflow"

            install = await client.post(
                "/api/v1/ssh/env/install",
                json={"target": "workflow_runtime", "profile_kind": "personal_docker"},
            )
            assert install.status_code == 200
            install_item = install.json()["item"]
            assert install_item["job_id"] == "job_runtime"
            assert runtime.install_calls == [{"target": "workflow_runtime", "tool_id": "", "profile_kind": "personal_docker"}]

            install_status = await client.get("/api/v1/ssh/env/install/job_runtime")
            assert install_status.status_code == 200
            assert install_status.json()["item"]["done"] is True

            docker_install = await client.post(
                "/api/v1/ssh/env/install",
                json={"target": "docker_runtime"},
            )
            assert docker_install.status_code == 200
            docker_install_item = docker_install.json()["item"]
            assert docker_install_item["target"] == "docker_runtime"
            assert runtime.install_calls[-1] == {"target": "docker_runtime", "tool_id": "", "profile_kind": ""}

    asyncio.run(exercise_routes())


def test_prepare_server_routes_surface_runtime_blockers_in_preflight(monkeypatch) -> None:
    runtime = _FakeRuntimeMissingJava()
    monkeypatch.setattr(api_main, "get_runtime_service", _RuntimeFactory(runtime))

    async def exercise_routes() -> None:
        transport = httpx.ASGITransport(app=api_main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            preflight = await client.post("/api/v1/ssh/preflight")
            assert preflight.status_code == 200
            preflight_item = preflight.json()["item"]
            assert preflight_item["ok"] is False
            assert "远端缺少 Java，无法运行 Nextflow" in preflight_item["failures"]
            assert preflight_item["checks"][0]["status"] == "fail"

    asyncio.run(exercise_routes())


def test_prepare_server_routes_allow_probe_resolve_mismatch_to_surface_as_failure(monkeypatch) -> None:
    runtime = _FakeRuntimeMissingJava()
    monkeypatch.setattr(api_main, "get_runtime_service", _RuntimeFactory(runtime))

    async def exercise_routes() -> None:
        transport = httpx.ASGITransport(app=api_main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            preflight = await client.post("/api/v1/ssh/preflight")
            assert preflight.status_code == 200
            preflight_item = preflight.json()["item"]
            assert preflight_item["ok"] is False
            assert preflight_item["runtime_capabilities"]["docker"]["usable"] is True
            assert preflight_item["runtime_capabilities"]["nextflow"]["usable"] is True
            assert "远端缺少 Java，无法运行 Nextflow" in preflight_item["failures"]

    asyncio.run(exercise_routes())
