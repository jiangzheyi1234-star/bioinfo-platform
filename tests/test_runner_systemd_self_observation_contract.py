from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from apps.remote_runner.systemd_self_observation import (
    capture_runner_systemd_self_observation,
    parse_runner_systemd_cgroup_candidates,
)
from core.contracts.linux_process_incarnation import (
    build_linux_process_incarnation,
)
from core.contracts.runner_systemd_self_observation import (
    RUNNER_SYSTEMD_SELF_OBSERVATION_EVIDENCE_PROFILE,
    RUNNER_SYSTEMD_SELF_OBSERVATION_MANAGER,
    RUNNER_SYSTEMD_SELF_OBSERVATION_SCHEMA,
    build_runner_systemd_self_observation,
    require_runner_systemd_self_observation,
    runner_systemd_self_observation_canonical_json,
    runner_systemd_self_observation_fingerprint,
)


ACTIVATION_ID = "1" * 32
INVOCATION_ID = "2" * 32
UNIT = f"h2ometa-remote@{ACTIVATION_ID}.service"
CGROUP_V2 = f"/user.slice/user-1000.slice/user@1000.service/app.slice/{UNIT}"
CGROUP_V1 = f"/user.slice/user-1000.slice/{UNIT}"


def _incarnation(*, pid: int = 4242) -> dict[str, object]:
    return build_linux_process_incarnation(
        boot_id="11111111-2222-3333-4444-555555555555",
        pid=pid,
        proc_start_ticks=987654,
    )


def _v2_candidate(*, path: str = CGROUP_V2) -> dict[str, object]:
    return {
        "controllers": [],
        "hierarchyId": 0,
        "path": path,
        "version": "v2",
    }


def _v1_candidate(
    *,
    hierarchy_id: int = 7,
    path: str = CGROUP_V1,
) -> dict[str, object]:
    return {
        "controllers": ["name=systemd"],
        "hierarchyId": hierarchy_id,
        "path": path,
        "version": "v1",
    }


def _observation() -> dict[str, object]:
    return build_runner_systemd_self_observation(
        invocation_id=INVOCATION_ID,
        unit=UNIT,
        process_incarnation=_incarnation(),
        cgroup_candidates=[_v2_candidate(), _v1_candidate()],
    )


def test_builds_exact_detached_hybrid_observation() -> None:
    incarnation = _incarnation()
    candidates = [_v2_candidate(), _v1_candidate()]

    observation = build_runner_systemd_self_observation(
        invocation_id=INVOCATION_ID,
        unit=UNIT,
        process_incarnation=incarnation,
        cgroup_candidates=candidates,
    )

    assert observation == {
        "cgroupCandidates": [_v2_candidate(), _v1_candidate()],
        "evidenceProfile": ("systemd-invocation-procfs-cgroup-candidates-v1"),
        "invocationId": INVOCATION_ID,
        "manager": "systemd-user",
        "processIncarnation": _incarnation(),
        "schemaVersion": "h2ometa.runner-systemd-self-observation.v1",
        "unit": UNIT,
    }
    assert observation["processIncarnation"] is not incarnation
    assert observation["cgroupCandidates"] is not candidates
    assert observation["cgroupCandidates"][0] is not candidates[0]

    incarnation["pid"] = 1
    candidates[0]["path"] = "/mutated"
    assert observation["processIncarnation"]["pid"] == 4242
    assert observation["cgroupCandidates"][0]["path"] == CGROUP_V2


def test_constants_are_exact() -> None:
    assert RUNNER_SYSTEMD_SELF_OBSERVATION_SCHEMA == (
        "h2ometa.runner-systemd-self-observation.v1"
    )
    assert RUNNER_SYSTEMD_SELF_OBSERVATION_EVIDENCE_PROFILE == (
        "systemd-invocation-procfs-cgroup-candidates-v1"
    )
    assert RUNNER_SYSTEMD_SELF_OBSERVATION_MANAGER == "systemd-user"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schemaVersion", "h2ometa.runner-systemd-self-observation.v0"),
        ("evidenceProfile", "other"),
        ("manager", "systemd-system"),
        ("invocationId", "A" * 32),
        ("invocationId", "1" * 31),
        ("unit", "h2ometa-remote.service"),
        ("unit", f"h2ometa-remote@{'A' * 32}.service"),
    ],
)
def test_contract_rejects_invalid_top_level_values(field: str, value: object) -> None:
    observation = _observation()
    observation[field] = value

    with pytest.raises(ValueError, match=field):
        require_runner_systemd_self_observation(observation)


def test_contract_requires_exact_top_level_and_candidate_fields() -> None:
    observation = _observation()
    observation["unexpected"] = True
    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_systemd_self_observation(observation)

    observation = _observation()
    del observation["manager"]
    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_systemd_self_observation(observation)

    observation = _observation()
    observation["cgroupCandidates"][0]["unexpected"] = True
    with pytest.raises(ValueError, match="candidate fields must match exactly"):
        require_runner_systemd_self_observation(observation)


@pytest.mark.parametrize(
    "candidates",
    [
        [],
        [_v2_candidate(), _v1_candidate(), _v1_candidate(hierarchy_id=8)],
        [_v2_candidate(), _v2_candidate()],
        [_v1_candidate(), _v2_candidate()],
        [{**_v2_candidate(), "version": "v3"}],
        [{**_v2_candidate(), "version": []}],
        [{**_v2_candidate(), "hierarchyId": True}],
        [{**_v2_candidate(), "hierarchyId": 1}],
        [{**_v2_candidate(), "controllers": ["name=systemd"]}],
        [{**_v1_candidate(), "hierarchyId": 0}],
        [{**_v1_candidate(), "controllers": []}],
        [{**_v1_candidate(), "controllers": ("name=systemd",)}],
    ],
)
def test_contract_rejects_noncanonical_candidate_sets(candidates: object) -> None:
    with pytest.raises(ValueError, match="cgroup"):
        build_runner_systemd_self_observation(
            invocation_id=INVOCATION_ID,
            unit=UNIT,
            process_incarnation=_incarnation(),
            cgroup_candidates=candidates,
        )


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "relative/path",
        f"//user.slice/{UNIT}",
        f"/user.slice/../{UNIT}",
        f"/user.slice/./{UNIT}",
        f"/user.slice/{UNIT}/",
        f"/user.slice\\{UNIT}",
        f"/user.slice/control\t/{UNIT}",
        f"/user.slice/{UNIT} (deleted)",
        f"/user.slice/other@{'3' * 32}.service",
    ],
)
def test_contract_rejects_unsafe_or_wrong_candidate_paths(path: str) -> None:
    with pytest.raises(ValueError, match="path"):
        build_runner_systemd_self_observation(
            invocation_id=INVOCATION_ID,
            unit=UNIT,
            process_incarnation=_incarnation(),
            cgroup_candidates=[_v2_candidate(path=path)],
        )


def test_contract_reuses_exact_process_incarnation_contract() -> None:
    incarnation = _incarnation()
    incarnation["pid"] = True

    with pytest.raises(ValueError, match="process incarnation pid"):
        build_runner_systemd_self_observation(
            invocation_id=INVOCATION_ID,
            unit=UNIT,
            process_incarnation=incarnation,
            cgroup_candidates=[_v2_candidate()],
        )


def test_canonical_json_and_fingerprint_are_stable_and_domain_separated() -> None:
    observation = _observation()
    reordered = dict(reversed(list(observation.items())))
    canonical = runner_systemd_self_observation_canonical_json(reordered)
    assert canonical == json.dumps(
        observation,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    expected = hashlib.sha256(
        RUNNER_SYSTEMD_SELF_OBSERVATION_SCHEMA.encode("ascii")
        + b"\x00"
        + canonical.encode("utf-8")
    ).hexdigest()
    assert runner_systemd_self_observation_fingerprint(observation) == (
        f"sha256:{expected}"
    )

    mutated = deepcopy(observation)
    mutated["cgroupCandidates"][0]["path"] = f"/other.slice/{UNIT}"
    assert runner_systemd_self_observation_fingerprint(mutated) != (
        runner_systemd_self_observation_fingerprint(observation)
    )


def test_parser_supports_exact_v2_candidate() -> None:
    assert parse_runner_systemd_cgroup_candidates(
        f"0::{CGROUP_V2}\n",
        systemd_unit=UNIT,
    ) == [_v2_candidate()]


def test_parser_preserves_colons_inside_the_cgroup_path() -> None:
    path = f"/user.slice/session:managed.scope/{UNIT}"

    assert parse_runner_systemd_cgroup_candidates(
        f"0::{path}\n",
        systemd_unit=UNIT,
    ) == [_v2_candidate(path=path)]


def test_parser_supports_exact_legacy_v1_systemd_candidate() -> None:
    assert parse_runner_systemd_cgroup_candidates(
        f"7:name=systemd:{CGROUP_V1}\n",
        systemd_unit=UNIT,
    ) == [_v1_candidate()]


def test_parser_retains_hybrid_candidates_in_canonical_order() -> None:
    raw = f"7:name=systemd:{CGROUP_V1}\n6:cpu,cpuacct:/user.slice\n0::{CGROUP_V2}\n"

    assert parse_runner_systemd_cgroup_candidates(
        raw,
        systemd_unit=UNIT,
    ) == [_v2_candidate(), _v1_candidate()]


def test_parser_ignores_unrelated_controller_only_after_safe_syntax() -> None:
    raw = f"9:memory:/\n8:pids:/user.slice\n0::{CGROUP_V2}\n"
    assert parse_runner_systemd_cgroup_candidates(
        raw,
        systemd_unit=UNIT,
    ) == [_v2_candidate()]

    with pytest.raises(ValueError, match="path"):
        parse_runner_systemd_cgroup_candidates(
            f"9:memory:relative\n0::{CGROUP_V2}\n",
            systemd_unit=UNIT,
        )


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "data"),
        (f"0::{CGROUP_V2}\n\n", "data"),
        (f"0::{CGROUP_V2}\r\n", "data"),
        (f"0::{CGROUP_V2}\x00", "data"),
        (f"0::{CGROUP_V2}\x7f", "data"),
        (f"0:{CGROUP_V2}", "shape"),
        (f"00::{CGROUP_V2}", "hierarchy"),
        (f"x::{CGROUP_V2}", "hierarchy"),
        (f"0:cpu:{CGROUP_V2}", "v2 controllers"),
        (f"7::{CGROUP_V1}", "v1 controllers"),
        (f"7:cpu,,pids:{CGROUP_V1}", "controllers"),
        (f"7:cpu,cpu:{CGROUP_V1}", "controllers"),
        (f"7:cpu/name:{CGROUP_V1}", "controllers"),
        (f"7:cpu,name=systemd:{CGROUP_V1}", "ambiguous"),
        ("7:memory:/", "unavailable"),
    ],
)
def test_parser_rejects_bad_line_shapes_and_ambiguous_controllers(
    raw: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_runner_systemd_cgroup_candidates(raw, systemd_unit=UNIT)


@pytest.mark.parametrize(
    "raw",
    [
        f"0::{CGROUP_V2}\n0::{CGROUP_V2}\n",
        f"7:name=systemd:{CGROUP_V1}\n8:name=systemd:{CGROUP_V1}\n",
    ],
)
def test_parser_rejects_duplicate_or_ambiguous_candidates(raw: str) -> None:
    with pytest.raises(ValueError, match="duplicated or ambiguous"):
        parse_runner_systemd_cgroup_candidates(raw, systemd_unit=UNIT)


@pytest.mark.parametrize(
    "path",
    [
        "/",
        f"/user.slice/../{UNIT}",
        f"/user.slice/./{UNIT}",
        f"/user.slice/{UNIT} (deleted)",
        f"/user.slice/not-{UNIT}",
        f"/user.slice/{UNIT}/",
        f"/user.slice\\{UNIT}",
    ],
)
def test_parser_rejects_root_namespace_escape_deleted_and_wrong_unit(
    path: str,
) -> None:
    with pytest.raises(ValueError, match="path"):
        parse_runner_systemd_cgroup_candidates(
            f"0::{path}\n",
            systemd_unit=UNIT,
        )


@pytest.mark.parametrize(
    "unit",
    [
        "h2ometa-remote.service",
        f"h2ometa-remote@{'A' * 32}.service",
        f"h2ometa-remote@{ACTIVATION_ID}.timer",
    ],
)
def test_parser_rejects_invalid_requested_unit(unit: str) -> None:
    with pytest.raises(ValueError, match="unit"):
        parse_runner_systemd_cgroup_candidates(
            f"0::{CGROUP_V2}\n",
            systemd_unit=unit,
        )


def _write_cgroup(proc_root: Path, *, pid: int, raw: str) -> None:
    process_dir = proc_root / str(pid)
    process_dir.mkdir(parents=True)
    (process_dir / "cgroup").write_text(raw, encoding="utf-8", newline="")


def test_capture_binds_environment_current_incarnation_and_exact_proc_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "apps.remote_runner.systemd_self_observation.os.getpid",
        lambda: 4242,
    )
    _write_cgroup(tmp_path, pid=4242, raw=f"0::{CGROUP_V2}\n")

    observation = capture_runner_systemd_self_observation(
        UNIT,
        _incarnation(),
        environ={
            "INVOCATION_ID": INVOCATION_ID,
            "SYSTEMD_EXEC_PID": "4242",
        },
        proc_root=tmp_path,
    )

    assert observation == build_runner_systemd_self_observation(
        invocation_id=INVOCATION_ID,
        unit=UNIT,
        process_incarnation=_incarnation(),
        cgroup_candidates=[_v2_candidate()],
    )


def test_capture_allows_absent_systemd_exec_pid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "apps.remote_runner.systemd_self_observation.os.getpid",
        lambda: 4242,
    )
    _write_cgroup(tmp_path, pid=4242, raw=f"7:name=systemd:{CGROUP_V1}\n")

    observation = capture_runner_systemd_self_observation(
        UNIT,
        _incarnation(),
        environ={"INVOCATION_ID": INVOCATION_ID},
        proc_root=tmp_path,
    )

    assert observation["cgroupCandidates"] == [_v1_candidate()]


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"INVOCATION_ID": ""},
        {"INVOCATION_ID": "A" * 32},
        {"INVOCATION_ID": "1" * 31},
        {"INVOCATION_ID": INVOCATION_ID, "SYSTEMD_EXEC_PID": ""},
        {"INVOCATION_ID": INVOCATION_ID, "SYSTEMD_EXEC_PID": "04242"},
        {"INVOCATION_ID": INVOCATION_ID, "SYSTEMD_EXEC_PID": "4243"},
        {"INVOCATION_ID": INVOCATION_ID, "SYSTEMD_EXEC_PID": 4242},
    ],
)
def test_capture_rejects_invalid_invocation_and_systemd_exec_pid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    environment: dict[str, object],
) -> None:
    monkeypatch.setattr(
        "apps.remote_runner.systemd_self_observation.os.getpid",
        lambda: 4242,
    )
    _write_cgroup(tmp_path, pid=4242, raw=f"0::{CGROUP_V2}\n")

    with pytest.raises(RuntimeError, match="self-observation is unavailable"):
        capture_runner_systemd_self_observation(
            UNIT,
            _incarnation(),
            environ=environment,
            proc_root=tmp_path,
        )


def test_capture_rejects_incarnation_for_another_pid_before_procfs_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "apps.remote_runner.systemd_self_observation.os.getpid",
        lambda: 4242,
    )

    with pytest.raises(RuntimeError, match="self-observation is unavailable"):
        capture_runner_systemd_self_observation(
            UNIT,
            _incarnation(pid=4243),
            environ={"INVOCATION_ID": INVOCATION_ID},
            proc_root=tmp_path,
        )


def test_capture_rejects_missing_invalid_and_oversized_exact_procfs_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "apps.remote_runner.systemd_self_observation.os.getpid",
        lambda: 4242,
    )
    environment = {"INVOCATION_ID": INVOCATION_ID}

    with pytest.raises(RuntimeError, match="self-observation is unavailable"):
        capture_runner_systemd_self_observation(
            UNIT,
            _incarnation(),
            environ=environment,
            proc_root=tmp_path,
        )

    _write_cgroup(tmp_path, pid=4242, raw=f"0::{CGROUP_V2} (deleted)\n")
    with pytest.raises(RuntimeError, match="self-observation is unavailable"):
        capture_runner_systemd_self_observation(
            UNIT,
            _incarnation(),
            environ=environment,
            proc_root=tmp_path,
        )

    cgroup_file = tmp_path / "4242" / "cgroup"
    cgroup_file.write_bytes(b"0::/" + b"x" * (64 * 1024))
    with pytest.raises(RuntimeError, match="self-observation is unavailable"):
        capture_runner_systemd_self_observation(
            UNIT,
            _incarnation(),
            environ=environment,
            proc_root=tmp_path,
        )
