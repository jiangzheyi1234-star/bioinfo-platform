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
