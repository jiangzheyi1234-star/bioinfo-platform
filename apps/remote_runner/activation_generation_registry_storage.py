"""Authoritative Linux storage for activation generation registrations.

The canonical registry is always rebuilt from immutable journal entries held
under an :class:`ActivationStorageSession`.  A caller-supplied registry or the
future ``generation-registry.json`` projection can never authorize an append.

This module deliberately stops at durable generation-ID reservation.  It does
not publish a generation directory and its result is not activation
``prepared`` evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import PurePosixPath
import re
import secrets
from typing import Literal

from core.contracts.runner_activation_generation_registry import (
    build_runner_activation_generation_registry,
    plan_runner_activation_generation_registry_append,
    require_runner_activation_generation_registration,
    require_runner_activation_generation_registry_binding,
    runner_activation_generation_registration_canonical_json,
    runner_activation_generation_registration_fingerprint,
    runner_activation_generation_registry_fingerprint,
)
from core.contracts.runner_activation_target import (
    require_runner_activation_generation,
)

from .activation_no_replace_io import (
    publish_file_no_replace,
    read_secure_regular_file,
)
from .activation_storage_session import (
    ActivationRegistrationAbsent,
    ActivationStorageConflict,
    ActivationStorageOutcomeUnknown,
    ActivationStorageSession,
)


GENERATION_REGISTRATION_FILE_MAX_BYTES = 64 * 1024
GENERATION_REGISTRATION_JOURNAL_MAX_BYTES = 64 * 1024 * 1024
GENERATION_REGISTRATION_JOURNAL_MAX_RECORDS = 10_000
GENERATION_REGISTRATION_REVISION_WIDTH = 20

_REGISTRATION_FILENAME = re.compile(r"^[0-9]{20}\.json$")


@dataclass(frozen=True, slots=True)
class GenerationRegistrationAppendObservation:
    """Redacted evidence derived only after a complete journal reread."""

    disposition: Literal[
        "created",
        "reconciled_exact",
        "already_registered_exact",
    ]
    registration_revision: int
    registration_fingerprint: str
    registry_fingerprint: str
    registry_revision: int


def rebuild_runner_activation_generation_registry(
    session: ActivationStorageSession,
) -> dict[str, object]:
    """Rebuild the canonical registry from every no-replace journal record."""

    session.require_open()
    # Every public rebuild first closes a prior process-level unknown window;
    # callers cannot obtain an "authoritative" prefix from page-cache
    # visibility alone.
    _close_unknown_directory_durability_window(session)
    registrations = _read_all_registration_records(session)
    try:
        registry = build_runner_activation_generation_registry(
            registrations,
            make_error=_storage_conflict,
        )
    except ActivationStorageConflict:
        raise
    except (TypeError, ValueError) as exc:  # Defensive contract boundary.
        raise _storage_conflict(
            "activation generation registration journal is invalid"
        ) from exc
    session.require_open()
    return registry


def append_runner_activation_generation_registration(
    session: ActivationStorageSession,
    *,
    generation: object,
) -> GenerationRegistrationAppendObservation:
    """Durably reserve one exact generation identity under the held gate.

    ``created`` means this call published the journal entry and then rebuilt
    the complete registry. ``reconciled_exact`` means ``RENAME_NOREPLACE`` saw
    an exact final record. ``already_registered_exact`` means the authoritative
    prefix already contained the exact generation before this call planned an
    append.  None of these dispositions proves a generation directory exists.
    """

    normalized_generation = _require_session_generation_binding(
        session,
        generation,
    )
    registry = rebuild_runner_activation_generation_registry(session)
    try:
        planned = plan_runner_activation_generation_registry_append(
            registry,
            generation=normalized_generation,
            make_error=_storage_conflict,
        )
    except ActivationStorageConflict:
        raise
    except (TypeError, ValueError) as exc:  # Defensive contract boundary.
        raise _storage_conflict(
            "activation generation registration append is invalid"
        ) from exc

    if planned is None:
        observation = _observation_from_registry(
            registry,
            generation=normalized_generation,
            disposition="already_registered_exact",
        )
        session.require_open()
        return observation

    revision = int(planned["revision"])
    destination_name = _registration_filename(revision)
    staging_name = (
        f"registration-{revision:0{GENERATION_REGISTRATION_REVISION_WIDTH}d}-"
        f"{secrets.token_hex(16)}.tmp"
    )
    payload = (
        runner_activation_generation_registration_canonical_json(
            planned,
            make_error=_storage_conflict,
        ).encode("utf-8")
        + b"\n"
    )
    _require_append_capacity(registry, payload=payload)
    publication = publish_file_no_replace(
        staging_fd=session.staging_fd,
        destination_fd=session.journal_fd,
        expected_device=session.device,
        staging_name=staging_name,
        destination_name=destination_name,
        payload=payload,
        max_bytes=GENERATION_REGISTRATION_FILE_MAX_BYTES,
    )
    try:
        rebuilt = rebuild_runner_activation_generation_registry(session)
        disposition: Literal["created", "reconciled_exact"] = (
            "created" if publication.disposition == "created" else "reconciled_exact"
        )
        observation = _observation_from_registry(
            rebuilt,
            generation=normalized_generation,
            disposition=disposition,
        )
        if (
            observation.registration_revision != revision
            or observation.registry_revision != revision
        ):
            raise _storage_conflict(
                "activation generation registration journal head changed unexpectedly"
            )
        session.require_open()
        return observation
    except ActivationStorageOutcomeUnknown:
        raise
    except Exception as exc:
        # Publication returned only after a rename/EEXIST durability proof.  If
        # its canonical root or the complete journal can no longer be proven,
        # callers must reconcile rather than infer that this append did not land.
        raise ActivationStorageOutcomeUnknown() from exc


def reconcile_runner_activation_generation_registration(
    session: ActivationStorageSession,
    *,
    generation: object,
) -> GenerationRegistrationAppendObservation:
    """Resolve a prior unknown append outcome from the authoritative journal.

    Absence is a typed non-success result: callers may retry only the exact
    generation after re-entering a fresh storage session.  A different record
    for the same generation ID is a permanent conflict.
    """

    normalized_generation = _require_session_generation_binding(
        session,
        generation,
    )
    registry = rebuild_runner_activation_generation_registry(session)
    registrations = registry["registrations"]
    if not isinstance(registrations, list):  # Contract invariant.
        raise _storage_conflict(
            "activation generation registration registry is invalid"
        )
    generation_id = str(normalized_generation["generationId"])
    matching = [
        registration
        for registration in registrations
        if registration["generationId"] == generation_id
    ]
    if not matching:
        raise ActivationRegistrationAbsent()
    if len(matching) != 1 or matching[0]["generation"] != normalized_generation:
        raise _storage_conflict("activation generation registration identity conflicts")
    observation = _observation_from_registry(
        registry,
        generation=normalized_generation,
        disposition="reconciled_exact",
    )
    session.require_open()
    return observation


def _close_unknown_directory_durability_window(
    session: ActivationStorageSession,
) -> None:
    try:
        os.fsync(session.staging_fd)
        os.fsync(session.journal_fd)
    except OSError as exc:
        raise ActivationStorageOutcomeUnknown() from exc


def _read_all_registration_records(
    session: ActivationStorageSession,
) -> list[dict[str, object]]:
    try:
        names = os.listdir(session.journal_fd)
    except OSError as exc:
        raise _storage_conflict(
            "activation generation registration journal is unreadable"
        ) from exc

    registration_names: list[tuple[int, str]] = []
    for name in names:
        if name == ".staging":
            continue
        if not isinstance(name, str) or _REGISTRATION_FILENAME.fullmatch(name) is None:
            raise _storage_conflict(
                "activation generation registration journal has an unexpected entry"
            )
        revision = int(name[:-5])
        if revision <= 0 or name != _registration_filename(revision):
            raise _storage_conflict(
                "activation generation registration filename is invalid"
            )
        registration_names.append((revision, name))

    registration_names.sort()
    if len(registration_names) > GENERATION_REGISTRATION_JOURNAL_MAX_RECORDS:
        raise _storage_conflict(
            "activation generation registration journal is too large"
        )

    result: list[dict[str, object]] = []
    total_bytes = 0
    for expected_revision, name in registration_names:
        raw = read_secure_regular_file(
            directory_fd=session.journal_fd,
            name=name,
            expected_device=session.device,
            max_bytes=GENERATION_REGISTRATION_FILE_MAX_BYTES,
        )
        total_bytes += len(raw)
        if total_bytes > GENERATION_REGISTRATION_JOURNAL_MAX_BYTES:
            raise _storage_conflict(
                "activation generation registration journal is too large"
            )
        registration = _decode_registration(raw)
        if int(registration["revision"]) != expected_revision:
            raise _storage_conflict(
                "activation generation registration filename does not match its revision"
            )
        result.append(registration)
    return result


def _require_append_capacity(
    registry: dict[str, object],
    *,
    payload: bytes,
) -> None:
    registrations = registry.get("registrations")
    if not isinstance(registrations, list):  # Contract invariant.
        raise _storage_conflict(
            "activation generation registration registry is invalid"
        )
    if len(registrations) + 1 > GENERATION_REGISTRATION_JOURNAL_MAX_RECORDS:
        raise _storage_conflict(
            "activation generation registration journal is too large"
        )
    current_bytes = 0
    for registration in registrations:
        current_bytes += (
            len(
                runner_activation_generation_registration_canonical_json(
                    registration,
                    make_error=_storage_conflict,
                ).encode("utf-8")
            )
            + 1
        )
    if current_bytes + len(payload) > GENERATION_REGISTRATION_JOURNAL_MAX_BYTES:
        raise _storage_conflict(
            "activation generation registration journal is too large"
        )


def _decode_registration(raw: bytes) -> dict[str, object]:
    try:
        text = raw.decode("utf-8", errors="strict")
        parsed = json.loads(text)
        registration = require_runner_activation_generation_registration(
            parsed,
            make_error=_storage_conflict,
        )
        expected = (
            runner_activation_generation_registration_canonical_json(
                registration,
                make_error=_storage_conflict,
            )
            + "\n"
        )
    except ActivationStorageConflict:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise _storage_conflict(
            "activation generation registration record is invalid"
        ) from exc
    if text != expected:
        raise _storage_conflict(
            "activation generation registration record is not canonical"
        )
    return registration


def _require_session_generation_binding(
    session: ActivationStorageSession,
    generation: object,
) -> dict[str, object]:
    session.require_open()
    try:
        normalized_generation = require_runner_activation_generation(
            generation,
            make_error=_storage_conflict,
        )
    except ActivationStorageConflict:
        raise
    except (TypeError, ValueError) as exc:  # Defensive contract boundary.
        raise _storage_conflict(
            "activation generation registration generation is invalid"
        ) from exc
    release_path = PurePosixPath(str(normalized_generation["releasePath"]))
    runner_root = str(release_path.parent.parent)
    if runner_root != session.installation["runnerRoot"]:
        raise _storage_conflict(
            "activation generation registration installation binding is invalid"
        )
    return normalized_generation


def _observation_from_registry(
    registry: dict[str, object],
    *,
    generation: dict[str, object],
    disposition: Literal[
        "created",
        "reconciled_exact",
        "already_registered_exact",
    ],
) -> GenerationRegistrationAppendObservation:
    try:
        registration_fingerprint = (
            require_runner_activation_generation_registry_binding(
                registry,
                generation=generation,
                make_error=_storage_conflict,
            )
        )
        registry_fingerprint = runner_activation_generation_registry_fingerprint(
            registry,
            make_error=_storage_conflict,
        )
    except ActivationStorageConflict:
        raise
    except (TypeError, ValueError) as exc:  # Defensive contract boundary.
        raise _storage_conflict(
            "activation generation registration registry binding is invalid"
        ) from exc
    registrations = registry["registrations"]
    if not isinstance(registrations, list):  # Contract invariant.
        raise _storage_conflict(
            "activation generation registration registry is invalid"
        )
    matching = next(
        registration
        for registration in registrations
        if registration["generationId"] == generation["generationId"]
    )
    expected_registration_fingerprint = (
        runner_activation_generation_registration_fingerprint(
            matching,
            make_error=_storage_conflict,
        )
    )
    if registration_fingerprint != expected_registration_fingerprint:
        raise _storage_conflict(
            "activation generation registration fingerprint is invalid"
        )
    return GenerationRegistrationAppendObservation(
        disposition=disposition,
        registration_revision=int(matching["revision"]),
        registration_fingerprint=registration_fingerprint,
        registry_fingerprint=registry_fingerprint,
        registry_revision=len(registrations),
    )


def _registration_filename(revision: int) -> str:
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision <= 0
        or revision >= 10**GENERATION_REGISTRATION_REVISION_WIDTH
    ):
        raise _storage_conflict(
            "activation generation registration revision is unsupported"
        )
    return f"{revision:0{GENERATION_REGISTRATION_REVISION_WIDTH}d}.json"


def _storage_conflict(message: str) -> ActivationStorageConflict:
    del message
    return ActivationStorageConflict()


__all__ = [
    "GENERATION_REGISTRATION_FILE_MAX_BYTES",
    "GENERATION_REGISTRATION_JOURNAL_MAX_BYTES",
    "GENERATION_REGISTRATION_JOURNAL_MAX_RECORDS",
    "GENERATION_REGISTRATION_REVISION_WIDTH",
    "GenerationRegistrationAppendObservation",
    "append_runner_activation_generation_registration",
    "rebuild_runner_activation_generation_registry",
    "reconcile_runner_activation_generation_registration",
]
