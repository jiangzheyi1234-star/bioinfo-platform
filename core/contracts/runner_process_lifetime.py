"""Shared constants for the cooperating runner process lifetime fence.

The lock is advisory and coordinates only runner processes that implement this
contract. Holding it does not prove listener ownership, process-tree ownership,
liveness, or death.
"""

from __future__ import annotations


RUNNER_PROCESS_LIFETIME_LOCK_FILENAME = "runner.lock"
RUNNER_PROCESS_LIFETIME_LAUNCHER_MODULE = (
    "remote_runner.runner_lifetime_launcher"
)
RUNNER_PROCESS_LIFETIME_LOCK_PROFILE = (
    "linux-flock-cooperating-single-instance-v1"
)
RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV = (
    "H2OMETA_RUNNER_PROCESS_LIFETIME_LOCK_FD"
)
RUNNER_PROCESS_LIFETIME_LOCK_HELD_EXIT_STATUS = 73
RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE_EXIT_STATUS = 74


__all__ = [
    "RUNNER_PROCESS_LIFETIME_LOCK_FILENAME",
    "RUNNER_PROCESS_LIFETIME_LAUNCHER_MODULE",
    "RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV",
    "RUNNER_PROCESS_LIFETIME_LOCK_HELD_EXIT_STATUS",
    "RUNNER_PROCESS_LIFETIME_LOCK_PROFILE",
    "RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE_EXIT_STATUS",
]
