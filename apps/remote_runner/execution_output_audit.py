from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .artifact_io import artifact_payload_stats
from .config import RemoteRunnerConfig
from .storage_core import get_connection


RUN_OUTPUT_AUDIT_SCHEMA_VERSION = "run-output-audit.v1"
RULE_OUTPUT_AUDIT_SCHEMA_VERSION = "rule-output-audit.v1"


def build_attempt_output_audit(
    *,
    run: dict[str, Any],
    attempts: list[dict[str, Any]],
    managed_work_dir: str | Path,
    managed_results_dir: str | Path,
) -> dict[str, Any]:
    latest = _latest_attempt_raw(attempts)
    base = {
        "schemaVersion": RUN_OUTPUT_AUDIT_SCHEMA_VERSION,
        "available": False,
        "pathExposed": False,
        "configAvailable": False,
        "expectedOutputCount": 0,
        "checkedOutputCount": 0,
        "existingOutputCount": 0,
        "missingOutputCount": 0,
        "verifiedOutputCount": 0,
        "checksumVerifiedOutputCount": 0,
        "rerunRequiredOutputCount": 0,
        "rerunRequired": False,
        "unsafeOutputCount": 0,
        "uncheckedOutputCount": 0,
        "unverifiedOutputCount": 0,
        "outputs": [],
    }
    if latest is None:
        return {**base, "reasonCode": "RUN_RESUME_NO_ATTEMPTS"}
    managed_work_root = Path(managed_work_dir).resolve(strict=False)
    managed_result_root = Path(managed_results_dir).resolve(strict=False)
    work_dir = _path_from(latest.get("workDir"))
    if work_dir is None:
        return {**base, "reasonCode": "WORKDIR_EVIDENCE_MISSING"}
    work_dir = work_dir.resolve(strict=False)
    if not _inside_any_root(work_dir, [managed_work_root]):
        return {**base, "reasonCode": "WORKDIR_OUTSIDE_MANAGED_ROOT"}
    config_path = work_dir / "run-config.json"
    if not config_path.exists():
        return {**base, "reasonCode": "RUN_CONFIG_NOT_FOUND"}
    config = _read_json_object(config_path)
    if config is None:
        return {**base, "configAvailable": True, "reasonCode": "RUN_CONFIG_INVALID"}
    outputs = config.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        return {**base, "configAvailable": True, "reasonCode": "RUN_CONFIG_OUTPUTS_MISSING"}

    safe_roots = _safe_roots(
        run=run,
        work_dir=work_dir,
        managed_result_root=managed_result_root,
    )
    audited = [_audit_output(name, value, work_dir=work_dir, safe_roots=safe_roots) for name, value in outputs.items()]
    existing_count = sum(1 for item in audited if item["state"] == "present")
    missing_count = sum(1 for item in audited if item["state"] == "missing")
    verified_count = sum(1 for item in audited if item.get("verificationState") == "verified")
    checksum_verified_count = sum(1 for item in audited if item.get("checksumVerified") is True)
    rerun_required_count = sum(1 for item in audited if item.get("rerunRequired") is True)
    unsafe_count = sum(1 for item in audited if item["state"] == "unsafe")
    unchecked_count = sum(1 for item in audited if item["state"] == "unchecked")
    unverified_count = sum(1 for item in audited if item.get("verificationState") == "unverified")
    checked_count = len(audited) - unchecked_count
    return {
        **base,
        "available": unsafe_count == 0 and unchecked_count == 0,
        "configAvailable": True,
        "expectedOutputCount": len(audited),
        "checkedOutputCount": checked_count,
        "existingOutputCount": existing_count,
        "missingOutputCount": missing_count,
        "verifiedOutputCount": verified_count,
        "checksumVerifiedOutputCount": checksum_verified_count,
        "rerunRequiredOutputCount": rerun_required_count,
        "rerunRequired": rerun_required_count > 0,
        "unsafeOutputCount": unsafe_count,
        "uncheckedOutputCount": unchecked_count,
        "unverifiedOutputCount": unverified_count,
        "reasonCode": _reason_code(
            existing_count=existing_count,
            missing_count=missing_count,
            verified_count=verified_count,
            rerun_required_count=rerun_required_count,
            unsafe_count=unsafe_count,
            unchecked_count=unchecked_count,
            unverified_count=unverified_count,
        ),
        "outputs": audited,
    }


def blocked_rule_retry_output_audit(reason_code: str = "RULE_OUTPUT_AUDIT_CONTEXT_UNAVAILABLE") -> dict[str, Any]:
    return {
        **_rule_output_audit_base(),
        "reasonCode": reason_code,
    }


def build_rule_retry_output_audit(
    *,
    cfg: RemoteRunnerConfig,
    run: dict[str, Any],
    attempts: list[dict[str, Any]],
    active_lease: dict[str, Any] | None,
    output_invalidation_plan: dict[str, Any],
    cache_restore_plan: dict[str, Any],
    managed_work_dir: str | Path,
    managed_results_dir: str | Path,
) -> dict[str, Any]:
    if not isinstance(output_invalidation_plan, dict) or output_invalidation_plan.get("previewAvailable") is not True:
        return blocked_rule_retry_output_audit(
            str(output_invalidation_plan.get("reasonCode") or "RULE_OUTPUT_AUDIT_INVALIDATION_UNAVAILABLE")
        )
    if _output_invalidation_applied(output_invalidation_plan) is not True:
        return _unchecked_rule_scope(cache_restore_plan, "RULE_OUTPUT_AUDIT_INVALIDATION_UNAPPLIED")
    if not isinstance(active_lease, dict):
        return _unchecked_rule_scope(cache_restore_plan, "RULE_OUTPUT_AUDIT_ACTIVE_LEASE_REQUIRED")
    attempt = _attempt_for_lease(attempts, active_lease)
    if attempt is None:
        return _unchecked_rule_scope(cache_restore_plan, "RULE_OUTPUT_AUDIT_ACTIVE_ATTEMPT_REQUIRED")
    work_dir = _path_from(attempt.get("workDir"))
    if work_dir is None:
        return _unchecked_rule_scope(cache_restore_plan, "WORKDIR_EVIDENCE_MISSING")
    managed_work_root = Path(managed_work_dir).resolve(strict=False)
    managed_result_root = Path(managed_results_dir).resolve(strict=False)
    work_dir = work_dir.resolve(strict=False)
    if not _inside_any_root(work_dir, [managed_work_root]):
        return _unsafe_rule_scope(cache_restore_plan, "WORKDIR_OUTSIDE_MANAGED_ROOT")
    config_path = work_dir / "run-config.json"
    if not config_path.exists():
        return _unchecked_rule_scope(cache_restore_plan, "RUN_CONFIG_NOT_FOUND")
    config = _read_json_object(config_path)
    if config is None:
        return _unchecked_rule_scope(cache_restore_plan, "RUN_CONFIG_INVALID")
    outputs = config.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        return _unchecked_rule_scope(cache_restore_plan, "RUN_CONFIG_OUTPUTS_MISSING")

    result_dir = _active_attempt_result_dir(
        managed_result_root,
        attempt_id=str(active_lease.get("attemptId") or ""),
        lease_generation=_safe_int(active_lease.get("leaseGeneration")),
    )
    safe_roots = _safe_roots(run=run, work_dir=work_dir, managed_result_root=managed_result_root)
    if _inside_any_root(result_dir, [managed_result_root]):
        safe_roots.append(result_dir)
    candidates = _candidate_rows(
        cfg,
        run_id=str(run.get("runId") or ""),
        attempt_id=str(active_lease.get("attemptId") or ""),
        lease_generation=_safe_int(active_lease.get("leaseGeneration")),
    )
    active_edges = _active_output_edges(cfg, run_id=str(run.get("runId") or ""))
    audited = [
        _audit_rule_retry_output(
            item,
            config_outputs=outputs,
            work_dir=work_dir,
            result_dir=result_dir,
            safe_roots=safe_roots,
            candidates=candidates,
            active_edges=active_edges,
        )
        for item in _rule_retry_outputs(cache_restore_plan)
    ]
    return _finalize_rule_output_audit(cache_restore_plan, audited)


def _rule_output_audit_base(cache_restore_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    cache_restore = _dict_value(cache_restore_plan)
    promotion = _dict_value(cache_restore.get("finalOutputPromotionState"))
    redaction = _dict_value(cache_restore.get("redactionPolicy"))
    return {
        "schemaVersion": RULE_OUTPUT_AUDIT_SCHEMA_VERSION,
        "available": False,
        "pathExposed": bool(redaction.get("pathsExposed")),
        "storageUriExposed": bool(redaction.get("storageUrisExposed")),
        "configAvailable": False,
        "expectedOutputCount": 0,
        "checkedOutputCount": 0,
        "existingOutputCount": 0,
        "missingOutputCount": 0,
        "adoptedOutputCount": _safe_int(promotion.get("adoptedCandidateOutputCount")),
        "verifiedOutputCount": 0,
        "checksumVerifiedOutputCount": 0,
        "rerunRequiredOutputCount": 0,
        "rerunRequired": False,
        "unsafeOutputCount": 0,
        "uncheckedOutputCount": 0,
        "unverifiedOutputCount": 0,
        "selectedOutputCount": 0,
        "downstreamOutputCount": 0,
        "cacheHitOutputCount": 0,
        "cacheMissOutputCount": 0,
        "outputs": [],
    }


def _finalize_rule_output_audit(cache_restore_plan: dict[str, Any], audited: list[dict[str, Any]]) -> dict[str, Any]:
    base = _rule_output_audit_base(cache_restore_plan)
    if not audited:
        return {**base, "reasonCode": str(cache_restore_plan.get("reasonCode") or "RULE_OUTPUT_AUDIT_SCOPE_EMPTY")}
    unsafe_count = sum(1 for item in audited if item["state"] == "unsafe")
    unchecked_count = sum(1 for item in audited if item["state"] == "unchecked")
    unverified_count = sum(1 for item in audited if item.get("verificationState") == "unverified")
    missing_count = sum(1 for item in audited if item["state"] == "missing")
    adopted_output_count = sum(1 for item in audited if item["state"] == "adopted")
    verified_count = sum(1 for item in audited if item.get("verificationState") == "verified")
    checksum_verified_count = sum(1 for item in audited if item.get("checksumVerified") is True)
    rerun_required_count = sum(1 for item in audited if item.get("rerunRequired") is True)
    cache_hit_count = sum(1 for item in audited if item.get("cacheHit") is True)
    cache_miss_count = sum(1 for item in audited if item.get("cacheHit") is False)
    selected_count = sum(1 for item in audited if item.get("invalidationRole") == "selected_failed_rule")
    downstream_count = sum(1 for item in audited if item.get("invalidationRole") == "downstream_rule")
    return {
        **base,
        "available": unsafe_count == 0 and unchecked_count == 0 and unverified_count == 0,
        "configAvailable": True,
        "expectedOutputCount": len(audited),
        "checkedOutputCount": len(audited) - unchecked_count,
        "existingOutputCount": adopted_output_count,
        "missingOutputCount": missing_count,
        "adoptedOutputCount": adopted_output_count,
        "verifiedOutputCount": verified_count,
        "checksumVerifiedOutputCount": checksum_verified_count,
        "rerunRequiredOutputCount": rerun_required_count,
        "rerunRequired": rerun_required_count > 0,
        "unsafeOutputCount": unsafe_count,
        "uncheckedOutputCount": unchecked_count,
        "unverifiedOutputCount": unverified_count,
        "selectedOutputCount": selected_count,
        "downstreamOutputCount": downstream_count,
        "cacheHitOutputCount": cache_hit_count,
        "cacheMissOutputCount": cache_miss_count,
        "reasonCode": _reason_code(
            existing_count=adopted_output_count,
            missing_count=missing_count,
            verified_count=verified_count,
            rerun_required_count=rerun_required_count,
            unsafe_count=unsafe_count,
            unchecked_count=unchecked_count,
            unverified_count=unverified_count,
        ),
        "outputs": audited,
    }


def _unchecked_rule_scope(cache_restore_plan: dict[str, Any], reason_code: str) -> dict[str, Any]:
    audited = [
        {
            **_rule_output_ref(item),
            "state": "unchecked",
            "verificationState": "unverified",
            "reasonCode": reason_code,
        }
        for item in _rule_retry_outputs(cache_restore_plan)
    ]
    return _finalize_rule_output_audit(cache_restore_plan, audited) if audited else {
        **_rule_output_audit_base(cache_restore_plan),
        "reasonCode": reason_code,
    }


def _unsafe_rule_scope(cache_restore_plan: dict[str, Any], reason_code: str) -> dict[str, Any]:
    audited = [
        {
            **_rule_output_ref(item),
            "state": "unsafe",
            "verificationState": "unverified",
            "reasonCode": reason_code,
        }
        for item in _rule_retry_outputs(cache_restore_plan)
    ]
    return _finalize_rule_output_audit(cache_restore_plan, audited) if audited else {
        **_rule_output_audit_base(cache_restore_plan),
        "reasonCode": reason_code,
    }


def _audit_output(
    name: Any,
    value: Any,
    *,
    work_dir: Path,
    safe_roots: list[Path],
) -> dict[str, Any]:
    key = str(name or "").strip()
    if not isinstance(value, str):
        return _unchecked(key, "OUTPUT_REFERENCE_INVALID")
    raw_path = str(value or "").strip()
    if not key or not raw_path:
        return _unchecked(key, "OUTPUT_REFERENCE_INVALID")
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = work_dir / candidate
    try:
        resolved = candidate.resolve(strict=False)
    except OSError:
        return _unchecked(key, "OUTPUT_PATH_UNRESOLVABLE")
    if not _inside_any_root(resolved, safe_roots):
        return {
            "key": key,
            "state": "unsafe",
            "verificationState": "unverified",
            "pathExposed": False,
            "reasonCode": "OUTPUT_PATH_OUTSIDE_MANAGED_ROOT",
        }
    if not resolved.exists():
        return {
            "key": key,
            "state": "missing",
            "verificationState": "verified",
            "rerunRequired": True,
            "pathExposed": False,
            "reasonCode": "OUTPUT_MISSING_RERUN_REQUIRED",
        }
    try:
        size_bytes, _sha256 = artifact_payload_stats(resolved)
    except (OSError, ValueError):
        return _unchecked(key, "OUTPUT_PAYLOAD_CHECKSUM_UNAVAILABLE")
    return {
        "key": key,
        "state": "present",
        "verificationState": "verified",
        "checksumVerified": True,
        "checksumAlgorithm": "sha256",
        "sizeBytes": size_bytes,
        "pathExposed": False,
        "reasonCode": "OUTPUT_PRESENT_CHECKSUM_VERIFIED",
    }


def _audit_rule_retry_output(
    item: dict[str, Any],
    *,
    config_outputs: dict[str, Any],
    work_dir: Path,
    result_dir: Path,
    safe_roots: list[Path],
    candidates: dict[str, dict[str, Any]],
    active_edges: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    output = _dict_value(item.get("output"))
    artifact_key = str(output.get("artifactKey") or "").strip()
    base = _rule_output_ref(item)
    if not artifact_key:
        return {
            **base,
            "state": "unchecked",
            "verificationState": "unverified",
            "reasonCode": "RULE_OUTPUT_ARTIFACT_KEY_UNMAPPED",
        }
    expected_path = _expected_rule_output_path(artifact_key, config_outputs, work_dir=work_dir, result_dir=result_dir)
    if expected_path is None:
        return {
            **base,
            "state": "unsafe",
            "verificationState": "unverified",
            "reasonCode": "RULE_OUTPUT_AUDIT_SCOPE_MISMATCH",
        }
    path_audit = _audit_output(artifact_key, str(expected_path), work_dir=work_dir, safe_roots=safe_roots)
    if path_audit["state"] in {"unsafe", "unchecked"}:
        return {
            **base,
            "state": path_audit["state"],
            "verificationState": "unverified",
            "reasonCode": path_audit["reasonCode"],
        }
    candidate = candidates.get(artifact_key)
    if candidate is not None:
        candidate_check = _candidate_verification(candidate, expected_path=expected_path)
        if candidate_check:
            return {
                **base,
                "state": "unsafe",
                "verificationState": "unverified",
                "reasonCode": candidate_check,
            }
        if str(candidate.get("adopted_artifact_id") or "").strip():
            active_edge_check = _active_edge_verification(
                active_edges,
                artifact_key=artifact_key,
                sha256=str(candidate.get("sha256") or ""),
            )
            if active_edge_check:
                return {
                    **base,
                    "state": "unsafe",
                    "verificationState": "unverified",
                    "reasonCode": active_edge_check,
                }
            return {
                **base,
                "state": "adopted",
                "verificationState": "verified",
                "checksumVerified": True,
                "checksumAlgorithm": "sha256",
                "reasonCode": "RULE_OUTPUT_ADOPTED_CHECKSUM_VERIFIED",
            }
        return {
            **base,
            "state": "present",
            "verificationState": "verified",
            "checksumVerified": True,
            "checksumAlgorithm": "sha256",
            "reasonCode": "RULE_OUTPUT_CANDIDATE_CHECKSUM_VERIFIED",
        }
    return {
        **base,
        "state": "missing",
        "verificationState": "verified",
        "rerunRequired": True,
        "reasonCode": "RULE_OUTPUT_RERUN_REQUIRED",
    }


def _rule_output_ref(item: dict[str, Any]) -> dict[str, Any]:
    output = _dict_value(item.get("output"))
    artifact_key = str(output.get("artifactKey") or "").strip()
    return {
        "outputOrdinal": _safe_int(output.get("outputOrdinal")),
        "invalidationRole": str(item.get("invalidationRole") or "").strip(),
        "stepId": str(output.get("stepId") or item.get("stepId") or "").strip(),
        "artifactKeyPresent": bool(artifact_key),
        "cacheHit": output.get("cacheHit") is True,
        "pathExposed": False,
    }


def _rule_retry_outputs(cache_restore: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for rule in cache_restore.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        for output in rule.get("outputs") or []:
            if isinstance(output, dict):
                items.append(
                    {
                        "invalidationRole": str(rule.get("invalidationRole") or ""),
                        "stepId": str(rule.get("stepId") or ""),
                        "ruleName": str(rule.get("ruleName") or ""),
                        "output": output,
                    }
                )
    return items


def _output_invalidation_applied(output_invalidation_plan: dict[str, Any]) -> bool:
    state = _dict_value(output_invalidation_plan.get("outputInvalidationState"))
    return state.get("state") == "applied" and _safe_int(state.get("appliedOutputEdgeCount")) > 0


def _attempt_for_lease(attempts: list[dict[str, Any]], active_lease: dict[str, Any]) -> dict[str, Any] | None:
    attempt_id = str(active_lease.get("attemptId") or "").strip()
    lease_generation = _safe_int(active_lease.get("leaseGeneration"))
    for attempt in attempts:
        if (
            str(attempt.get("attemptId") or "").strip() == attempt_id
            and _safe_int(attempt.get("leaseGeneration")) == lease_generation
        ):
            return attempt
    return None


def _active_attempt_result_dir(root: Path, *, attempt_id: str, lease_generation: int) -> Path:
    return (root / "attempts" / attempt_id / f"generation-{lease_generation}").resolve(strict=False)


def _candidate_rows(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
) -> dict[str, dict[str, Any]]:
    if not run_id or not attempt_id or lease_generation <= 0:
        return {}
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM candidate_outputs
            WHERE run_id = ? AND attempt_id = ? AND lease_generation = ?
            ORDER BY output_key ASC
            """,
            (run_id, attempt_id, lease_generation),
        ).fetchall()
    return {str(row["output_key"] or ""): dict(row) for row in rows}


def _active_output_edges(cfg: RemoteRunnerConfig, *, run_id: str) -> dict[str, list[dict[str, Any]]]:
    if not run_id:
        return {}
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM run_artifact_edges
            WHERE run_id = ? AND role = 'output' AND lifecycle_state = 'active'
            ORDER BY created_at ASC, edge_id ASC
            """,
            (run_id,),
        ).fetchall()
    by_key: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_key.setdefault(str(row["port_name"] or ""), []).append(dict(row))
    return by_key


def _expected_rule_output_path(
    artifact_key: str,
    config_outputs: dict[str, Any],
    *,
    work_dir: Path,
    result_dir: Path,
) -> Path | None:
    if artifact_key not in config_outputs:
        return None
    raw = config_outputs[artifact_key]
    if isinstance(raw, dict):
        raw = raw.get("path")
    text = str(raw or "").strip()
    if not text:
        return None
    candidate = Path(text)
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    result_candidate = (result_dir / candidate).resolve(strict=False)
    work_candidate = (work_dir / candidate).resolve(strict=False)
    return result_candidate if result_dir in result_candidate.parents or result_candidate == result_dir else work_candidate


def _candidate_verification(candidate: dict[str, Any], *, expected_path: Path) -> str:
    candidate_path = _path_from(candidate.get("path"))
    if candidate_path is None:
        return "RULE_OUTPUT_AUDIT_CANDIDATE_PATH_MISSING"
    if candidate_path.resolve(strict=False) != expected_path.resolve(strict=False):
        return "RULE_OUTPUT_AUDIT_CANDIDATE_MISMATCH"
    try:
        size_bytes, sha256 = artifact_payload_stats(expected_path)
    except (OSError, ValueError):
        return "RULE_OUTPUT_AUDIT_CANDIDATE_CHECKSUM_UNAVAILABLE"
    if _safe_int(candidate.get("size_bytes")) != int(size_bytes):
        return "RULE_OUTPUT_AUDIT_CANDIDATE_MISMATCH"
    if str(candidate.get("sha256") or "") != sha256:
        return "RULE_OUTPUT_AUDIT_CANDIDATE_MISMATCH"
    return ""


def _active_edge_verification(
    active_edges: dict[str, list[dict[str, Any]]],
    *,
    artifact_key: str,
    sha256: str,
) -> str:
    matching_edges = [
        edge
        for edge in active_edges.get(artifact_key, [])
        if str(edge.get("content_hash") or "") == sha256
    ]
    return "" if matching_edges else "RULE_OUTPUT_AUDIT_ADOPTED_EDGE_MISMATCH"


def _safe_roots(
    *,
    run: dict[str, Any],
    work_dir: Path,
    managed_result_root: Path,
) -> list[Path]:
    roots = [work_dir.resolve(strict=False)]
    result_dir = _path_from(run.get("resultDir"))
    if result_dir is not None:
        resolved_result_dir = result_dir.resolve(strict=False)
        if _inside_any_root(resolved_result_dir, [managed_result_root]):
            roots.append(resolved_result_dir)
    roots.append(managed_result_root)
    return roots


def _reason_code(
    *,
    existing_count: int,
    missing_count: int,
    verified_count: int,
    rerun_required_count: int,
    unsafe_count: int,
    unchecked_count: int,
    unverified_count: int,
) -> str:
    if unsafe_count:
        return "OUTPUT_AUDIT_UNSAFE_REFERENCES"
    if unchecked_count:
        return "OUTPUT_AUDIT_UNCHECKED_REFERENCES"
    if unverified_count:
        return "OUTPUT_AUDIT_UNVERIFIED_OUTPUTS"
    if missing_count and rerun_required_count == missing_count:
        return "OUTPUT_AUDIT_RERUN_REQUIRED"
    if existing_count:
        return "OUTPUT_AUDIT_VERIFIED"
    if verified_count:
        return "OUTPUT_AUDIT_VERIFIED"
    return "OUTPUT_AUDIT_EMPTY"


def _unchecked(key: str, reason_code: str) -> dict[str, Any]:
    return {
        "key": key,
        "state": "unchecked",
        "verificationState": "unverified",
        "pathExposed": False,
        "reasonCode": reason_code,
    }


def _inside_any_root(path: Path, roots: list[Path]) -> bool:
    return any(root == path or root in path.parents for root in roots)


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _path_from(value: Any) -> Path | None:
    text = str(value or "").strip()
    return Path(text) if text else None


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _latest_attempt_raw(attempts: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not attempts:
        return None
    return max(
        attempts,
        key=lambda attempt: (
            _optional_int(attempt.get("attemptNumber")),
            _optional_int(attempt.get("leaseGeneration")),
            str(attempt.get("updatedAt") or ""),
        ),
    )


def _optional_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
