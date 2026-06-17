"""部署模式配置管理。

定义三种产品模式：
- desktop: 单用户本地桌面应用
- server-single-user: 单用户可信内网服务器部署
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
        if not self.allows_public_network:
            if host not in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
                raise ValueError(
                    f"Deployment mode '{self.mode}' does not allow binding to '{host}'. "
                    f"Use a reverse proxy for external access."
                )
            if host == "0.0.0.0" and self.mode == DeploymentMode.DESKTOP:
                raise ValueError(
                    "Desktop mode does not allow binding to 0.0.0.0. "
                    "Use 127.0.0.1, localhost, or ::1."
                )
            if host == "0.0.0.0" and self.mode == DeploymentMode.SERVER_SINGLE_USER:
                import warnings
                warnings.warn(
                    f"Deployment mode '{self.mode}' is bound to 0.0.0.0. "
                    "This mode is intended for trusted intranet only. "
                    "Do not expose to public internet without proper authentication.",
                    stacklevel=2,
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
        description="单用户可信内网服务器部署，使用环境变量存储敏感信息，禁止公网暴露",
    ),
    DeploymentMode.SERVER_MULTI_USER: DeploymentConfig(
        mode=DeploymentMode.SERVER_MULTI_USER,
        requires_auth=True,
        allows_public_network=True,
        credential_storage="database-encrypted",
        description="多用户服务器部署，需要完整认证、RBAC 和审计日志",
    ),
}


def get_deployment_mode() -> DeploymentMode:
    """从环境变量获取当前部署模式。"""
    mode_str = os.environ.get("H2OMETA_DEPLOYMENT_MODE", "desktop").strip().lower()
    try:
        return DeploymentMode(mode_str)
    except ValueError:
        return DeploymentMode.DESKTOP


def get_deployment_config() -> DeploymentConfig:
    """获取当前部署模式的配置。"""
    mode = get_deployment_mode()
    return DEPLOYMENT_CONFIGS[mode]


def validate_deployment_security() -> list[str]:
    """验证部署安全配置，返回警告列表。"""
    warnings: list[str] = []
    config = get_deployment_config()

    if config.mode == DeploymentMode.SERVER_SINGLE_USER:
        host = os.environ.get("H2OMETA_API_HOST", "127.0.0.1")
        if host == "0.0.0.0":
            warnings.append(
                "server-single-user 模式绑定到 0.0.0.0，请确保仅在内网访问，"
                "不要直接暴露到公网"
            )

        if not os.environ.get("H2OMETA_RUNNER_TOKEN"):
            warnings.append(
                "server-single-user 模式未设置 H2OMETA_RUNNER_TOKEN，"
                "Remote Runner API 将无法认证"
            )

    if config.mode == DeploymentMode.SERVER_MULTI_USER:
        if not os.environ.get("H2OMETA_AUTH_SECRET"):
            warnings.append(
                "server-multi-user 模式需要设置 H2OMETA_AUTH_SECRET 用于 JWT 签名"
            )

    return warnings
