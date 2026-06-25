from __future__ import annotations

from typing import Any

from .secret_provider import (
    SUPPORTED_SECRET_PURPOSES,
    SUPPORTED_SECRET_REF_SCHEMES,
    default_webhook_secret_provider_schemes,
)


SECRET_PROVIDER_READINESS_SCHEMA_VERSION = "remote-runner-secret-provider-readiness.v1"


def build_secret_provider_readiness() -> dict[str, Any]:
    default_schemes = set(default_webhook_secret_provider_schemes())
    providers = [
        _provider_status(scheme, default_enabled=scheme in default_schemes)
        for scheme in sorted(SUPPORTED_SECRET_REF_SCHEMES)
    ]
    return {
        "schemaVersion": SECRET_PROVIDER_READINESS_SCHEMA_VERSION,
        "supportedPurposes": sorted(SUPPORTED_SECRET_PURPOSES),
        "defaultWebhookProviderSchemes": sorted(default_schemes),
        "providers": providers,
        "redactionPolicy": {
            "rawReferencesExposed": False,
            "secretValuesExposed": False,
            "individualReferenceProbing": False,
        },
    }


def _provider_status(scheme: str, *, default_enabled: bool) -> dict[str, Any]:
    provider_kind = {
        "env": "environment",
        "keyring": "os-keyring",
        "secret": "remote-runner-secret",
        "vault": "external-vault",
    }[scheme]
    if default_enabled:
        return {
            "scheme": scheme,
            "providerKind": provider_kind,
            "defaultForWebhookSigning": True,
            "state": "available",
            "reasonCode": "",
            "resolutionBoundary": "provider-integration",
        }
    return {
        "scheme": scheme,
        "providerKind": provider_kind,
        "defaultForWebhookSigning": False,
        "state": "unconfigured",
        "reasonCode": "SECRET_PROVIDER_UNAVAILABLE",
        "resolutionBoundary": "fail-closed",
    }
