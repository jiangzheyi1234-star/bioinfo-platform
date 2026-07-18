#!/usr/bin/env python3
"""Isolated in-method EINTR signal-dispatch probes for the proof module."""

from __future__ import annotations

import argparse
import errno
import importlib
import os
import signal
import stat
import sys
import sysconfig
import tempfile
from pathlib import Path


class InMethodSignalError(RuntimeError):
    pass


_LIFECYCLE_FIELDS = (
    "owner_allocations",
    "capsule_creation_successes",
    "pretransfer_owner_frees",
    "destructor_calls",
    "destructor_owner_frees",
    "fd_adoptions",
    "fd_consumptions",
    "namespace_mutations",
    "eintr_conversions",
    "sigint_raise_calls",
    "handler_dispatch_inside",
    "handler_dispatch_outside",
    "inside_errno_conversion",
    "boundary_owner_state",
    "boundary_namespace_state",
    "last_errno",
)


def _fd_set() -> set[int]:
    descriptors = {int(name) for name in os.listdir("/proc/self/fd")}
    live: set[int] = set()
    for descriptor in descriptors:
        try:
            os.fstat(descriptor)
        except OSError:
            continue
        live.add(descriptor)
    return live


def _matching_fds(device: int, inode: int) -> set[int]:
    matches: set[int] = set()
    for descriptor in _fd_set():
        try:
            status = os.fstat(descriptor)
        except OSError:
            continue
        if (status.st_dev, status.st_ino) == (device, inode):
            matches.add(descriptor)
    return matches


def _counter(snapshot: dict[str, object], name: str) -> int:
    value = snapshot[name]
    if not isinstance(value, int):
        raise AssertionError(f"snapshot counter is invalid: {name}={value!r}")
    return value


def _snapshot(module) -> dict[str, object]:
    lifecycle = module._test_lifecycle_snapshot()
    leaf = module._test_leaf_snapshot()
    if not isinstance(lifecycle, tuple) or len(lifecycle) != 16:
        raise AssertionError("lifecycle snapshot has an invalid shape")
    if not isinstance(leaf, tuple) or len(leaf) != 4:
        raise AssertionError("leaf snapshot has an invalid shape")
    mkdir, fchmod, fsync, reproof = leaf
    if not isinstance(mkdir, tuple) or len(mkdir) != 5:
        raise AssertionError("mkdir snapshot has an invalid shape")
    if not isinstance(fchmod, tuple) or len(fchmod) != 4:
        raise AssertionError("fchmod snapshot has an invalid shape")
    if not isinstance(fsync, tuple) or len(fsync) != 3:
        raise AssertionError("fsync snapshot has an invalid shape")
    if not isinstance(reproof, tuple) or len(reproof) != 6:
        raise AssertionError("reproof snapshot has an invalid shape")
    snapshot: dict[str, object] = dict(zip(_LIFECYCLE_FIELDS, lifecycle))
    snapshot["mkdirat_calls"] = mkdir[0]
    snapshot["fchmod_calls"] = fchmod[0]
    snapshot["fsync_calls"] = fsync[0]
    return snapshot


def _run_probe(*, site: Path, scenario: str, expected_minor: str) -> None:
    actual_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
    if sys.implementation.name != "cpython" or actual_minor != expected_minor:
        raise RuntimeError(
            f"unexpected probe interpreter: {sys.implementation.name} {actual_minor}"
        )
    if sys.version_info[:2] not in {(3, 12), (3, 13), (3, 14)}:
        raise RuntimeError(f"unsupported CPython minor: {actual_minor}")
    if sysconfig.get_config_var("Py_GIL_DISABLED"):
        raise RuntimeError("EINTR proof requires a standard-GIL CPython build")

    sys.path.insert(0, str(site))
    module = importlib.import_module(
        "remote_runner._activation_release_dir_owner_proof"
    )
    required_hooks = {
        "_test_arm_sigint_for_next_eintr",
        "_test_duplicate_directory",
        "_test_leaf_snapshot",
        "_test_lifecycle_snapshot",
        "_test_note_signal_handler_dispatch",
        "_test_set_fchmod_errno",
        "_test_set_fsync_errno",
        "_test_set_mkdirat_errno",
        "_test_set_openat2_errnos",
    }
    missing = required_hooks - set(vars(module))
    if missing:
        raise RuntimeError(f"native owner proof module is missing hooks: {missing}")

    module._test_reset()
    with tempfile.TemporaryDirectory(prefix="h2ometa-native-owner-eintr-") as raw:
        root = Path(raw) / "parent"
        root.mkdir(mode=0o700)
        raw_parent = os.open(
            root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
        )
        parent = module._test_duplicate_directory(raw_parent)
        os.close(raw_parent)
        baseline_fds = _fd_set()
        before = _snapshot(module)

        child_path = root / f"child-{scenario}"
        if scenario == "mkdir":
            module._test_set_mkdirat_errno(errno.EINTR)
        elif scenario == "open":
            module._test_set_openat2_errnos((errno.EINTR,))
        elif scenario == "fchmod":
            module._test_set_fchmod_errno(errno.EINTR)
        elif scenario == "fsync":
            module._test_set_fsync_errno(errno.EINTR)
        else:
            raise AssertionError(scenario)
        module._test_arm_sigint_for_next_eintr()

        handler_calls = 0

        def handle_sigint(_signum, _frame):
            nonlocal handler_calls
            handler_calls += 1
            module._test_note_signal_handler_dispatch()
            raise InMethodSignalError("signal dispatched inside errno conversion")

        previous_handler = signal.signal(signal.SIGINT, handle_sigint)
        try:
            try:
                if scenario == "fsync":
                    module._fsync_directory(parent)
                else:
                    module._mkdir_child(parent, child_path.name)
            except InMethodSignalError:
                pass
            else:
                raise AssertionError("pending SIGINT did not replace EINTR")
        finally:
            signal.signal(signal.SIGINT, previous_handler)

        after = _snapshot(module)
        if handler_calls != 1:
            raise AssertionError(f"unexpected handler count: {handler_calls}")
        if (
            _counter(after, "eintr_conversions") - _counter(before, "eintr_conversions")
            != 1
        ):
            raise AssertionError("EINTR was not converted exactly once")
        if (
            _counter(after, "sigint_raise_calls")
            - _counter(before, "sigint_raise_calls")
            != 1
        ):
            raise AssertionError("SIGINT was not raised exactly once")
        if (
            _counter(after, "handler_dispatch_inside")
            - _counter(before, "handler_dispatch_inside")
            != 1
        ):
            raise AssertionError("handler did not run inside errno conversion")
        if _counter(after, "handler_dispatch_outside") != _counter(
            before, "handler_dispatch_outside"
        ):
            raise AssertionError("handler ran after the native method returned")
        if _counter(after, "inside_errno_conversion") != 0:
            raise AssertionError("errno conversion flag was not cleared")
        if _counter(after, "last_errno") != errno.EINTR:
            raise AssertionError("EINTR was not the converted errno")
        if _fd_set() != baseline_fds:
            raise AssertionError("descriptor set changed across EINTR dispatch")

        if scenario == "mkdir":
            if child_path.exists():
                raise AssertionError("pre-mutation EINTR created a directory")
            expected_boundary = (0, 0)
            expected_calls = (1, 0, 0, 0)
        elif scenario == "open":
            expected_boundary = (0, 1)
            expected_calls = (1, 1, 0, 0)
        elif scenario == "fchmod":
            expected_boundary = (0, 1)
            expected_calls = (1, 1, 1, 0)
        else:
            expected_boundary = (1, 0)
            expected_calls = (0, 0, 0, 1)

        actual_boundary = (
            _counter(after, "boundary_owner_state"),
            _counter(after, "boundary_namespace_state"),
        )
        if actual_boundary != expected_boundary:
            raise AssertionError(
                f"unexpected boundary state: {actual_boundary} != {expected_boundary}"
            )
        actual_calls = (
            _counter(after, "mkdirat_calls") - _counter(before, "mkdirat_calls"),
            int(module._test_attempt_snapshot()[0]),
            _counter(after, "fchmod_calls") - _counter(before, "fchmod_calls"),
            _counter(after, "fsync_calls") - _counter(before, "fsync_calls"),
        )
        if actual_calls != expected_calls:
            raise AssertionError(
                f"unexpected syscall calls: {actual_calls} != {expected_calls}"
            )

        if scenario in {"open", "fchmod"}:
            child_status = child_path.stat()
            if not stat.S_ISDIR(child_status.st_mode):
                raise AssertionError("markerless orphan is not a directory")
            if _matching_fds(child_status.st_dev, child_status.st_ino):
                raise AssertionError("markerless orphan descriptor leaked")
        if scenario == "fsync":
            module._require_live(parent)
        module._close(parent)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument(
        "--scenario",
        choices=("mkdir", "open", "fchmod", "fsync"),
        required=True,
    )
    parser.add_argument("--expected-minor", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _run_probe(
        site=args.site,
        scenario=args.scenario,
        expected_minor=args.expected_minor,
    )
    print(
        f"NATIVE_OWNER_EINTR_OK scenario={args.scenario} python={args.expected_minor}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
