from __future__ import annotations

from pathlib import Path

from core.governance_policy import HIGH_RISK_API_POLICIES, validate_governance_policy
from scripts.security_governance_audit import scan_governance_policy_contracts


ROOT = Path(__file__).resolve().parents[1]


def _tracked_policy_sources() -> list[Path]:
    sources = {ROOT / "core" / "governance_policy.py"}
    sources.update(ROOT / policy.route_source for policy in HIGH_RISK_API_POLICIES)
    sources.update(
        {
            ROOT / "apps" / "remote_runner" / "audit_service.py",
            ROOT / "apps" / "remote_runner" / "artifact_lifecycle_service.py",
            ROOT / "apps" / "remote_runner" / "artifact_product_service.py",
            ROOT / "apps" / "remote_runner" / "control_service.py",
            ROOT / "apps" / "remote_runner" / "database_service.py",
            ROOT / "apps" / "remote_runner" / "result_package_byte_gc_service.py",
            ROOT / "apps" / "remote_runner" / "result_package_lifecycle_service.py",
            ROOT / "apps" / "remote_runner" / "run_reexecution_service.py",
            ROOT / "apps" / "remote_runner" / "submission_service.py",
            ROOT / "apps" / "remote_runner" / "tool_service.py",
            ROOT / "apps" / "remote_runner" / "trigger_observability_governance.py",
            ROOT / "apps" / "remote_runner" / "trigger_service.py",
        }
    )
    return sorted(sources)


def test_high_risk_governance_policy_is_explicit_and_blocked_for_multi_user() -> None:
    assert validate_governance_policy() == []
    assert len(HIGH_RISK_API_POLICIES) >= 20
    assert {policy.current_boundary for policy in HIGH_RISK_API_POLICIES} == {
        "desktop-localhost-only",
        "remote-runner-bearer-token",
    }
    assert all(not policy.multi_user_ready for policy in HIGH_RISK_API_POLICIES)
    assert all(policy.future_roles for policy in HIGH_RISK_API_POLICIES)
    assert any(policy.audit_status == "required-before-multi-user" for policy in HIGH_RISK_API_POLICIES)


def test_high_risk_governance_policy_routes_and_implemented_audit_actions_exist() -> None:
    implementation_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in _tracked_policy_sources()
        if path.relative_to(ROOT).as_posix().startswith("apps/remote_runner/")
    )
    for policy in HIGH_RISK_API_POLICIES:
        route_source = (ROOT / policy.route_source).read_text(encoding="utf-8")
        route_decorator = "websocket" if policy.method == "WEBSOCKET" else policy.method.lower()
        assert f'"{policy.route}"' in route_source
        assert f"@router.{route_decorator}(" in route_source
        if policy.audit_status == "implemented":
            assert f'action="{policy.action}"' in implementation_source
            if policy.surface == "remote-runner-api":
                assert (
                    f'action="{policy.action}"' in implementation_source
                    and (
                        f'authorized_config(authorization, action="{policy.action}")' in implementation_source
                        or f'_authorized_config_from_request(authorization, action="{policy.action}")'
                        in implementation_source
                    )
                )


def test_security_governance_audit_enforces_governance_policy_contracts() -> None:
    assert scan_governance_policy_contracts(_tracked_policy_sources()) == []
