"""部署模式配置管理。

定义三种产品模式：
- desktop: 单用户本地桌面应用
- server-single-user: 单用户服务器草案，当前仅允许 localhost/API 反向代理边界
- server-multi-user: 多用户服务器部署（需要完整认证和 RBAC）
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.env_bool import parse_strict_env_bool


class DeploymentMode(str, Enum):
    DESKTOP = "desktop"
    SERVER_SINGLE_USER = "server-single-user"
    SERVER_MULTI_USER = "server-multi-user"


class DeploymentModeError(ValueError):
    pass


class UnsupportedDeploymentModeError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeploymentConfig:
    mode: DeploymentMode
    requires_auth: bool
    allows_public_network: bool
    credential_storage: str
    description: str

    @property
    def is_single_user(self) -> bool:
        return self.mode in (DeploymentMode.DESKTOP, DeploymentMode.SERVER_SINGLE_USER)

    @property
    def is_server_mode(self) -> bool:
        return self.mode in (DeploymentMode.SERVER_SINGLE_USER, DeploymentMode.SERVER_MULTI_USER)

    def validate_network_binding(self, host: str) -> None:
        """验证网络绑定是否符合安全策略。"""
        normalized_host = host.strip().lower()
        if not self.allows_public_network:
            if normalized_host not in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
                raise ValueError(
                    f"Deployment mode '{self.mode}' does not allow binding to '{host}'. "
                    f"Use a reverse proxy for external access."
                )
            if normalized_host == "0.0.0.0" and self.mode == DeploymentMode.DESKTOP:
                raise ValueError(
                    "Desktop mode does not allow binding to 0.0.0.0. "
                    "Use 127.0.0.1, localhost, or ::1."
                )
            if normalized_host == "0.0.0.0" and self.mode == DeploymentMode.SERVER_SINGLE_USER:
                raise ValueError(
                    "server-single-user mode does not allow binding to 0.0.0.0. "
                    "Bind the API to 127.0.0.1, localhost, or ::1 and put any network access "
                    "behind an authenticated reverse proxy."
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "requiresAuth": self.requires_auth,
            "allowsPublicNetwork": self.allows_public_network,
            "credentialStorage": self.credential_storage,
            "description": self.description,
            "isSingleUser": self.is_single_user,
            "isServerMode": self.is_server_mode,
        }


PRODUCTION_GOVERNANCE_SCHEMA_VERSION = "production-governance-readiness.v1"
DATABASE_URL_ENV_NAMES = (
    "H2OMETA_DATABASE_URL",
    "H2OMETA_REMOTE_RUNNER_DATABASE_URL",
    "DATABASE_URL",
)
DEPLOYMENT_CONFIGS: dict[DeploymentMode, DeploymentConfig] = {
    DeploymentMode.DESKTOP: DeploymentConfig(
        mode=DeploymentMode.DESKTOP,
        requires_auth=False,
        allows_public_network=False,
        credential_storage="os-keyring",
        description="单用户本地桌面应用，使用操作系统凭据存储",
    ),
    DeploymentMode.SERVER_SINGLE_USER: DeploymentConfig(
        mode=DeploymentMode.SERVER_SINGLE_USER,
        requires_auth=False,
        allows_public_network=False,
        credential_storage="env-secret",
        description="单用户服务器草案，API 当前仅允许 localhost 绑定，外部访问需先完成认证反向代理验收",
    ),
    DeploymentMode.SERVER_MULTI_USER: DeploymentConfig(
        mode=DeploymentMode.SERVER_MULTI_USER,
        requires_auth=True,
        allows_public_network=True,
        credential_storage="database-encrypted",
        description="多用户服务器部署，需要完整认证、RBAC 和审计日志",
    ),
}


SUPPORTED_DEPLOYMENT_MODES = {
    DeploymentMode.DESKTOP,
    DeploymentMode.SERVER_SINGLE_USER,
}


def get_deployment_mode() -> DeploymentMode:
    """从环境变量获取当前部署模式。"""
    raw_mode = os.environ.get("H2OMETA_DEPLOYMENT_MODE")
    mode_str = raw_mode.strip().lower() if raw_mode is not None else ""
    if not mode_str:
        raise DeploymentModeError(
            "H2OMETA_DEPLOYMENT_MODE is required. Set it explicitly to desktop or server-single-user."
        )
    try:
        return DeploymentMode(mode_str)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in DeploymentMode)
        raise DeploymentModeError(
            f"Invalid H2OMETA_DEPLOYMENT_MODE '{mode_str}'. Expected one of: {allowed}."
        ) from exc


def get_deployment_config() -> DeploymentConfig:
    """获取当前部署模式的配置。"""
    mode = get_deployment_mode()
    return DEPLOYMENT_CONFIGS[mode]


def require_supported_deployment_mode() -> DeploymentConfig:
    """Fail closed for modes whose security boundary is not implemented."""
    config = get_deployment_config()
    if config.mode not in SUPPORTED_DEPLOYMENT_MODES:
        raise UnsupportedDeploymentModeError(
            "H2OMETA_DEPLOYMENT_MODE=server-multi-user is not implemented. "
            "Do not enable it until authentication, RBAC, tenant isolation, "
            "secret vault integration, and organization audit boundaries are complete."
        )
    return config


def validate_deployment_security() -> list[str]:
    """验证部署安全配置，返回警告列表。"""
    warnings: list[str] = []
    config = require_supported_deployment_mode()
    host = os.environ.get("H2OMETA_API_HOST", "127.0.0.1")
    config.validate_network_binding(host)

    if config.mode == DeploymentMode.SERVER_SINGLE_USER:
        if not os.environ.get("H2OMETA_RUNNER_TOKEN"):
            warnings.append(
                "server-single-user 模式未设置 H2OMETA_RUNNER_TOKEN，"
                "Remote Runner API 将无法认证"
            )

    return warnings


def build_production_governance_readiness() -> dict[str, Any]:
    """Return a safe readiness projection for production governance gates."""
    config = get_deployment_config()
    host = os.environ.get("H2OMETA_API_HOST", "127.0.0.1")
    mode_supported = config.mode in SUPPORTED_DEPLOYMENT_MODES
    network_status, network_reason, network_blocks_current = _network_gate(config, host)
    runner_token_configured = bool(os.environ.get("H2OMETA_RUNNER_TOKEN", "").strip())
    database_signal_present = _any_env_signal_present(DATABASE_URL_ENV_NAMES)
    s3_signals = _s3_signal_summary()
    s3_status, s3_reason = _s3_gate(s3_signals)

    checks = [
        _readiness_check(
            "deployment-mode-supported",
            "pass" if mode_supported else "blocked",
            "DEPLOYMENT_MODE_SUPPORTED" if mode_supported else "SERVER_MULTI_USER_UNSUPPORTED",
            config.mode is DeploymentMode.SERVER_MULTI_USER,
            "Current launch mode is one of the source-controlled supported modes.",
            ("core/deployment_mode.py", "docs/deployment-modes.md"),
            {"mode": config.mode.value, "supportedModes": sorted(mode.value for mode in SUPPORTED_DEPLOYMENT_MODES)},
        ),
        _readiness_check(
            "network-binding-boundary",
            network_status,
            network_reason,
            network_blocks_current,
            "Supported local/server modes keep the API on localhost or behind an authenticated proxy.",
            ("core/deployment_mode.py", "docs/deployment-modes.md"),
            {
                "bindAllRequested": host.strip().lower() == "0.0.0.0",
                "externalHostRequested": host.strip().lower()
                not in ("", "127.0.0.1", "localhost", "::1", "0.0.0.0"),
            },
        ),
        _readiness_check(
            "remote-runner-machine-token",
            _machine_token_status(config, runner_token_configured),
            _machine_token_reason(config, runner_token_configured),
            config.mode is DeploymentMode.SERVER_SINGLE_USER and not runner_token_configured,
            "Server single-user mode requires an authenticated machine-token boundary before runner APIs are useful.",
            ("core/governance_policy.py", "docs/security-governance.md"),
            {"configured": runner_token_configured, "scope": "machine-token"},
        ),
        _readiness_check(
            "multi-user-identity-rbac",
            "blocked",
            "AUTH_RBAC_TENANT_MODEL_PENDING",
            config.mode is DeploymentMode.SERVER_MULTI_USER,
            "Public multi-user mode still needs identity, per-user RBAC, tenant/project resource ownership, and route-level enforcement.",
            ("core/governance_policy.py", "docs/security-governance.md"),
            {"machineTokenBoundaryOnly": True, "publicMultiUserReady": False},
        ),
        _readiness_check(
            "postgres-control-plane",
            "blocked" if database_signal_present else "pending",
            "POSTGRES_UNSUPPORTED_SIGNAL_PRESENT" if database_signal_present else "POSTGRES_REPOSITORY_LAYER_PENDING",
            database_signal_present,
            "PostgreSQL remains disabled until repository, transaction, migration, and multi-user governance boundaries are implemented.",
            ("apps/remote_runner/database_backend_config.py", "docs/deployment-modes.md"),
            {"databaseUrlSignalPresent": database_signal_present, "supportedBackend": "sqlite"},
        ),
        _readiness_check(
            "s3-minio-artifact-storage",
            s3_status,
            s3_reason,
            False,
            "S3/MinIO may be used only through the managed artifact adapter and managed-prefix checks.",
            ("apps/remote_runner/artifact_io.py", "docs/security-governance.md"),
            s3_signals,
        ),
        _readiness_check(
            "secret-provider-boundary",
            "partial",
            "VAULT_AND_SECRET_SCHEMES_FAIL_CLOSED",
            False,
            "Secret references resolve through explicit providers; keyring is adapter-backed, while secret:// and vault:// remain disabled.",
            ("apps/remote_runner/secret_provider.py", "docs/security-governance.md"),
            {"rawSecretValuesReturned": False, "unconfiguredProvidersFailClosed": True},
        ),
        _readiness_check(
            "audit-release-gates",
            "pass",
            "HASH_CHAINED_AUDIT_AND_RELEASE_GATES_PRESENT",
            False,
            "High-risk actions emit hash-chained governance audit records and CI/release promotion gates are source-controlled.",
            ("apps/remote_runner/governance_audit.py", ".github/workflows/promote-remote-runner-release.yml"),
            {"releasePromotionEnvironment": "production-runtime", "directMainProtectionPolicy": "source-controlled"},
        ),
    ]
    current_blockers = [check["id"] for check in checks if check["blocksCurrentMode"] and check["status"] == "blocked"]
    public_multi_user_blockers = [
        check["id"] for check in checks if check["status"] in ("blocked", "pending", "partial")
    ]
    return {
        "schemaVersion": PRODUCTION_GOVERNANCE_SCHEMA_VERSION,
        "currentModeStatus": "blocked" if current_blockers else "ready",
        "publicMultiUserStatus": "blocked",
        "publicMultiUserReady": False,
        "currentModeBlockingCheckIds": current_blockers,
        "publicMultiUserBlockingCheckIds": public_multi_user_blockers,
        "checks": checks,
    }


def _readiness_check(
    check_id: str,
    status: str,
    reason_code: str,
    blocks_current_mode: bool,
    summary: str,
    evidence: tuple[str, ...],
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": status,
        "reasonCode": reason_code,
        "blocksCurrentMode": blocks_current_mode,
        "requiredFor": "server-multi-user",
        "summary": summary,
        "evidence": list(evidence),
        "details": details,
    }


def _network_gate(config: DeploymentConfig, host: str) -> tuple[str, str, bool]:
    try:
        config.validate_network_binding(host)
    except ValueError:
        return "blocked", "NETWORK_BINDING_UNSUPPORTED", True
    return "pass", "NETWORK_BINDING_SUPPORTED", False


def _machine_token_status(config: DeploymentConfig, configured: bool) -> str:
    if config.mode is DeploymentMode.DESKTOP:
        return "not_applicable"
    return "pass" if configured else "blocked"


def _machine_token_reason(config: DeploymentConfig, configured: bool) -> str:
    if config.mode is DeploymentMode.DESKTOP:
        return "DESKTOP_LOCAL_BOUNDARY"
    return "REMOTE_RUNNER_TOKEN_CONFIGURED" if configured else "REMOTE_RUNNER_TOKEN_REQUIRED"


def _any_env_signal_present(names: tuple[str, ...]) -> bool:
    return any(bool(os.environ.get(name, "").strip()) for name in names)


def _s3_signal_summary() -> dict[str, bool]:
    endpoint = bool(os.environ.get("H2OMETA_ARTIFACT_S3_ENDPOINT", "").strip())
    bucket = bool(os.environ.get("H2OMETA_ARTIFACT_S3_BUCKET", "").strip())
    access_key = bool(os.environ.get("H2OMETA_ARTIFACT_S3_ACCESS_KEY", "").strip())
    secret_key = bool(os.environ.get("H2OMETA_ARTIFACT_S3_SECRET_KEY", "").strip())
    prefix = bool(os.environ.get("H2OMETA_ARTIFACT_S3_PREFIX", "").strip())
    secure_transport_value_valid = True
    try:
        secure_transport_requested = bool(
            parse_strict_env_bool(
                os.environ.get("H2OMETA_ARTIFACT_S3_SECURE"),
                name="H2OMETA_ARTIFACT_S3_SECURE",
                default=True,
            )
        )
    except ValueError:
        secure_transport_requested = False
        secure_transport_value_valid = False
    return {
        "endpointConfigured": endpoint,
        "bucketConfigured": bucket,
        "credentialPairConfigured": access_key and secret_key,
        "managedPrefixConfigured": prefix,
        "secureTransportRequested": secure_transport_requested,
        "secureTransportValueValid": secure_transport_value_valid,
        "complete": endpoint and bucket and access_key and secret_key and prefix,
    }


def _s3_gate(signals: dict[str, bool]) -> tuple[str, str]:
    if not signals["secureTransportValueValid"]:
        return "partial", "S3_MINIO_SECURE_TRANSPORT_INVALID"
    if not signals["complete"]:
        return "pending", "S3_MINIO_CONFIGURATION_PENDING"
    if not signals["secureTransportRequested"]:
        return "partial", "S3_MINIO_SECURE_TRANSPORT_PENDING"
    return "pass", "S3_MINIO_CONFIGURED"
