from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
import hashlib
import inspect
import json
from pathlib import Path, PureWindowsPath
import re
from types import MappingProxyType

import pytest

import core.contracts.runner_activation_keyring as keyring_contract
from core.contracts.runner_activation_keyring import (
    RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_RELATIVE_DIRECTORY,
    RUNNER_ACTIVATION_INSTALLATION_SCHEMA,
    RUNNER_ACTIVATION_TOKEN_OS_KEYRING_NAMESPACE,
    RUNNER_ACTIVATION_TOKEN_PROVIDER_KIND,
    RUNNER_ACTIVATION_TOKEN_PURPOSE,
    RUNNER_ACTIVATION_TOKEN_REF_PREFIX,
    RUNNER_ACTIVATION_TOKEN_REF_SCHEMA,
    RunnerActivationTokenKeyringLocator,
    build_new_runner_activation_installation,
    build_runner_activation_installation,
    build_runner_activation_token_keyring_locator,
    build_runner_activation_token_ref,
    new_runner_activation_installation_id,
    require_runner_activation_installation,
    require_runner_activation_token_ref,
    runner_activation_config_integrity_key_path,
    runner_activation_installation_canonical_json,
    runner_activation_installation_fingerprint,
    runner_activation_token_ref_fingerprint,
)
from tests.helpers.runner_activation_contract import ROOT


INSTALLATION_ID = "e" * 32
OTHER_INSTALLATION_ID = "a" * 32
TOKEN_GENERATION_ID = "b" * 32
OTHER_TOKEN_GENERATION_ID = "c" * 32
CONFIG_INTEGRITY_KEY_ID = "d" * 32
SECRET_SENTINEL = "credential-material-must-never-appear"


class KeyringContractError(Exception):
    pass


def _installation(
    *,
    installation_id: str = INSTALLATION_ID,
    runner_root: str = ROOT,
) -> dict[str, object]:
    return build_runner_activation_installation(
        runner_installation_id=installation_id,
        runner_root=runner_root,
    )


def _token_ref(
    installation: object | None = None,
    *,
    token_generation_id: str = TOKEN_GENERATION_ID,
) -> str:
    return build_runner_activation_token_ref(
        installation=_installation() if installation is None else installation,
        token_generation_id=token_generation_id,
    )


def _domain_fingerprint(schema: str, canonical: str) -> str:
    digest = hashlib.sha256(
        schema.encode("ascii") + b"\x00" + canonical.encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def test_installation_builder_is_exact_detached_and_domain_fingerprinted() -> None:
    built = _installation()
    expected = {
        "runnerInstallationId": INSTALLATION_ID,
        "runnerRoot": ROOT,
        "schemaVersion": RUNNER_ACTIVATION_INSTALLATION_SCHEMA,
        "service": "h2ometa-remote",
    }

    assert built == expected
    normalized = require_runner_activation_installation(MappingProxyType(built))
    assert normalized == expected
    assert normalized is not built
    canonical = runner_activation_installation_canonical_json(built)
    assert canonical == json.dumps(
        expected,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert runner_activation_installation_fingerprint(built) == _domain_fingerprint(
        RUNNER_ACTIVATION_INSTALLATION_SCHEMA,
        canonical,
    )

    built["runnerRoot"] = "/tampered/.h2ometa/runner"
    assert normalized == expected


def test_new_installation_ids_are_opaque_lowercase_128_bit_values() -> None:
    first_id = new_runner_activation_installation_id()
    second_id = new_runner_activation_installation_id()
    built = build_new_runner_activation_installation(runner_root=ROOT)

    assert re.fullmatch(r"[0-9a-f]{32}", first_id)
    assert re.fullmatch(r"[0-9a-f]{32}", second_id)
    assert first_id != second_id
    assert re.fullmatch(r"[0-9a-f]{32}", str(built["runnerInstallationId"]))
    assert built["runnerRoot"] == ROOT


@pytest.mark.parametrize(
    "runner_root",
    [
        "",
        "/",
        "/etc",
        "/home/runner",
        "/home/runner/runner",
        "home/runner/.h2ometa/runner",
        "//home/runner/.h2ometa/runner",
        "/home/runner/.h2ometa/runner/",
        "/home//runner/.h2ometa/runner",
        "/home/./runner/.h2ometa/runner",
        "/home/runner/../runner/.h2ometa/runner",
        "/home/runner/.h2ometa\\runner",
        " /home/runner/.h2ometa/runner",
        "/home/runner/.h2ometa/runner ",
        "/home/runner/.h2ometa/runner\x00",
        "/home/runner/.h2ometa/runner\x1f",
        "/home/runner/.h2ometa/runner\x7f",
        "/home/runner/.h2ometa/runner\x80",
        "/home/runner/.h2ometa/runner\x85",
        "/home/runner/.h2ometa/runner\x9f",
        "/home/runner/.h2ometa/runner\u2028",
        "/home/runner/.h2ometa/runner\u2029",
        "/home/runner/.h2ometa/runner\ud800",
    ],
)
def test_installation_rejects_noncanonical_or_wrongly_scoped_roots(
    runner_root: str,
) -> None:
    with pytest.raises(ValueError, match="runnerRoot is invalid"):
        _installation(runner_root=runner_root)


@pytest.mark.parametrize(
    "runner_root",
    [PureWindowsPath(r"C:\h2ometa\.h2ometa\runner"), Path("relative")],
)
def test_installation_rejects_host_pathlike_coercion(runner_root: object) -> None:
    with pytest.raises(ValueError, match="runnerRoot is invalid"):
        build_runner_activation_installation(
            runner_installation_id=INSTALLATION_ID,
            runner_root=runner_root,
        )


def test_installation_root_reserves_space_for_the_full_material_path() -> None:
    material_suffix = (
        f"/{RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_RELATIVE_DIRECTORY}/"
        f"{CONFIG_INTEGRITY_KEY_ID}.key"
    )
    root_suffix = "/.h2ometa/runner"
    max_root_bytes = 4095 - len(material_suffix.encode("ascii"))
    component_length = max_root_bytes - len(root_suffix.encode("ascii")) - 1
    boundary_root = f"/{'a' * component_length}{root_suffix}"

    installation = _installation(runner_root=boundary_root)
    material_path = runner_activation_config_integrity_key_path(
        installation=installation,
        config_integrity_key_id=CONFIG_INTEGRITY_KEY_ID,
    )
    assert len(material_path.encode("utf-8")) == 4095
    with pytest.raises(ValueError, match="runnerRoot is invalid"):
        _installation(runner_root=f"/{'a' * (component_length + 1)}{root_suffix}")
    with pytest.raises(ValueError, match="runnerRoot is invalid"):
        _installation(runner_root=f"/{'é' * component_length}{root_suffix}")


@pytest.mark.parametrize(
    "installation_id",
    [
        "",
        "1" * 31,
        "1" * 33,
        "A" * 32,
        "g" * 32,
        " " + "1" * 32,
        "1" * 32 + "\n",
        b"1" * 32,
        None,
        1,
    ],
)
def test_installation_id_is_exact_lowercase_hex(installation_id: object) -> None:
    with pytest.raises(ValueError, match="runnerInstallationId is invalid"):
        build_runner_activation_installation(
            runner_installation_id=installation_id,
            runner_root=ROOT,
        )


def test_installation_schema_and_fields_are_closed() -> None:
    valid = _installation()
    invalid_payloads: list[object] = [None, [], "installation"]
    for field, value in (
        ("schemaVersion", "h2ometa.runner-activation-installation.v2"),
        ("service", "other-service"),
        ("runnerInstallationId", OTHER_INSTALLATION_ID.upper()),
        ("runnerRoot", "/etc"),
    ):
        payload = dict(valid)
        payload[field] = value
        invalid_payloads.append(payload)
    extra = dict(valid)
    extra["hostId"] = "not-authoritative"
    invalid_payloads.append(extra)
    missing = dict(valid)
    del missing["runnerRoot"]
    invalid_payloads.append(missing)

    for payload in invalid_payloads:
        with pytest.raises(ValueError):
            require_runner_activation_installation(payload)


def test_token_reference_is_exact_context_bound_and_envelope_fingerprinted() -> None:
    installation = _installation()
    token_ref = _token_ref(installation)
    expected = (
        f"{RUNNER_ACTIVATION_TOKEN_REF_PREFIX}:{INSTALLATION_ID}:{TOKEN_GENERATION_ID}"
    )
    assert token_ref == expected
    assert (
        require_runner_activation_token_ref(
            token_ref,
            installation=installation,
            token_generation_id=TOKEN_GENERATION_ID,
        )
        == expected
    )

    envelope = {
        "keyringNamespace": RUNNER_ACTIVATION_TOKEN_OS_KEYRING_NAMESPACE,
        "providerKind": RUNNER_ACTIVATION_TOKEN_PROVIDER_KIND,
        "purpose": RUNNER_ACTIVATION_TOKEN_PURPOSE,
        "schemaVersion": RUNNER_ACTIVATION_TOKEN_REF_SCHEMA,
        "service": "h2ometa-remote",
        "tokenRef": token_ref,
    }
    canonical_envelope = json.dumps(
        envelope,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    fingerprint = runner_activation_token_ref_fingerprint(
        token_ref,
        installation=installation,
        token_generation_id=TOKEN_GENERATION_ID,
    )
    assert fingerprint == _domain_fingerprint(
        RUNNER_ACTIVATION_TOKEN_REF_SCHEMA,
        canonical_envelope,
    )
    assert fingerprint != f"sha256:{hashlib.sha256(token_ref.encode()).hexdigest()}"


def test_token_keyring_locator_has_one_fixed_namespace_and_hidden_account() -> None:
    installation = _installation()
    token_ref = _token_ref(installation)
    locator = build_runner_activation_token_keyring_locator(
        installation=installation,
        token_generation_id=TOKEN_GENERATION_ID,
    )

    assert RUNNER_ACTIVATION_TOKEN_PROVIDER_KIND == "os-keyring"
    assert RUNNER_ACTIVATION_TOKEN_PURPOSE == "runner-api-token"
    assert locator.service_name == RUNNER_ACTIVATION_TOKEN_OS_KEYRING_NAMESPACE
    assert locator.account_name == token_ref
    assert token_ref not in repr(locator)
    assert "account_name" not in repr(locator)
    with pytest.raises(TypeError, match="use build"):
        RunnerActivationTokenKeyringLocator()
    with pytest.raises(FrozenInstanceError):
        locator.service_name = "caller-controlled"


def test_same_token_generation_id_is_namespaced_by_installation() -> None:
    first_installation = _installation()
    second_installation = _installation(installation_id=OTHER_INSTALLATION_ID)
    first_ref = _token_ref(first_installation)
    second_ref = _token_ref(second_installation)

    assert first_ref != second_ref
    assert runner_activation_token_ref_fingerprint(
        first_ref,
        installation=first_installation,
        token_generation_id=TOKEN_GENERATION_ID,
    ) != runner_activation_token_ref_fingerprint(
        second_ref,
        installation=second_installation,
        token_generation_id=TOKEN_GENERATION_ID,
    )


@pytest.mark.parametrize(
    "token_ref",
    [
        "runner://server-id",
        f"h2ometa-runner-token:v1:{INSTALLATION_ID}:{TOKEN_GENERATION_ID}",
        f"h2ometa-runner-token:V2:{INSTALLATION_ID}:{TOKEN_GENERATION_ID}",
        f"H2OMeta-runner-token:v2:{INSTALLATION_ID}:{TOKEN_GENERATION_ID}",
        f"{RUNNER_ACTIVATION_TOKEN_REF_PREFIX}:{INSTALLATION_ID.upper()}:{TOKEN_GENERATION_ID}",
        f"{RUNNER_ACTIVATION_TOKEN_REF_PREFIX}:{INSTALLATION_ID}:{TOKEN_GENERATION_ID.upper()}",
        f" {RUNNER_ACTIVATION_TOKEN_REF_PREFIX}:{INSTALLATION_ID}:{TOKEN_GENERATION_ID}",
        f"{RUNNER_ACTIVATION_TOKEN_REF_PREFIX}:{INSTALLATION_ID}:{TOKEN_GENERATION_ID} ",
        f"{RUNNER_ACTIVATION_TOKEN_REF_PREFIX}/{INSTALLATION_ID}/{TOKEN_GENERATION_ID}",
        f"{RUNNER_ACTIVATION_TOKEN_REF_PREFIX}:{INSTALLATION_ID}/{TOKEN_GENERATION_ID}",
        f"{RUNNER_ACTIVATION_TOKEN_REF_PREFIX}:{INSTALLATION_ID}::{TOKEN_GENERATION_ID}",
        f"{RUNNER_ACTIVATION_TOKEN_REF_PREFIX}:{INSTALLATION_ID}:{TOKEN_GENERATION_ID}:extra",
        f"{RUNNER_ACTIVATION_TOKEN_REF_PREFIX}:{INSTALLATION_ID}",
        f"{RUNNER_ACTIVATION_TOKEN_REF_PREFIX}:{INSTALLATION_ID}:{TOKEN_GENERATION_ID}\n",
    ],
)
def test_token_reference_rejects_legacy_or_malformed_grammar(token_ref: str) -> None:
    with pytest.raises(ValueError, match="token reference is invalid"):
        require_runner_activation_token_ref(
            token_ref,
            installation=_installation(),
            token_generation_id=TOKEN_GENERATION_ID,
        )


def test_token_reference_rejects_context_mismatch_and_role_collision() -> None:
    installation = _installation()
    token_ref = _token_ref(installation)

    with pytest.raises(ValueError, match="token reference is invalid"):
        require_runner_activation_token_ref(
            token_ref,
            installation=_installation(installation_id=OTHER_INSTALLATION_ID),
            token_generation_id=TOKEN_GENERATION_ID,
        )
    with pytest.raises(ValueError, match="token reference is invalid"):
        require_runner_activation_token_ref(
            token_ref,
            installation=installation,
            token_generation_id=OTHER_TOKEN_GENERATION_ID,
        )

    colliding_installation = _installation(installation_id=TOKEN_GENERATION_ID)
    with pytest.raises(ValueError, match="identifier roles must be distinct"):
        build_runner_activation_token_ref(
            installation=colliding_installation,
            token_generation_id=TOKEN_GENERATION_ID,
        )
    with pytest.raises(ValueError, match="identifier roles must be distinct"):
        require_runner_activation_token_ref(
            (
                f"{RUNNER_ACTIVATION_TOKEN_REF_PREFIX}:"
                f"{TOKEN_GENERATION_ID}:{TOKEN_GENERATION_ID}"
            ),
            installation=colliding_installation,
            token_generation_id=TOKEN_GENERATION_ID,
        )


def test_token_surfaces_require_complete_trusted_context() -> None:
    functions = (
        build_runner_activation_token_keyring_locator,
        build_runner_activation_token_ref,
        require_runner_activation_token_ref,
        runner_activation_token_ref_fingerprint,
    )
    for function in functions:
        signature = inspect.signature(function)
        for name in ("installation", "token_generation_id"):
            parameter = signature.parameters[name]
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
            assert parameter.default is inspect.Parameter.empty
    assert (
        "keyring_namespace"
        not in inspect.signature(
            build_runner_activation_token_keyring_locator
        ).parameters
    )


def test_custom_errors_do_not_echo_token_reference_or_invalid_values() -> None:
    installation = _installation()

    def make_error(message: str) -> KeyringContractError:
        return KeyringContractError(f"custom: {message}")

    calls = [
        lambda: require_runner_activation_installation(
            {"secret": SECRET_SENTINEL}, make_error=make_error
        ),
        lambda: runner_activation_installation_fingerprint(
            {"secret": SECRET_SENTINEL}, make_error=make_error
        ),
        lambda: runner_activation_token_ref_fingerprint(
            SECRET_SENTINEL,
            installation=installation,
            token_generation_id=TOKEN_GENERATION_ID,
            make_error=make_error,
        ),
        lambda: build_runner_activation_token_keyring_locator(
            installation=installation,
            token_generation_id=INSTALLATION_ID,
            make_error=make_error,
        ),
    ]
    for call in calls:
        with pytest.raises(KeyringContractError, match="^custom:") as captured:
            call()
        assert SECRET_SENTINEL not in str(captured.value)


def test_module_is_pure_dormant_and_has_no_legacy_or_context_free_surface() -> None:
    source = Path(keyring_contract.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    called_names: set[str] = set()
    called_attributes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_attributes.add(node.func.attr)

    assert imported_roots.isdisjoint(
        {
            "apps",
            "config",
            "io",
            "keyring",
            "os",
            "shutil",
            "socket",
            "subprocess",
            "tempfile",
        }
    )
    assert "open" not in called_names
    assert called_attributes.isdisjoint(
        {"read_bytes", "read_text", "write_bytes", "write_text"}
    )
    assert "runner://" not in source
    assert not any(name.startswith("parse_runner") for name in keyring_contract.__all__)
    assert all(
        "material" not in name for name in keyring_contract.__all__ if "token" in name
    )
