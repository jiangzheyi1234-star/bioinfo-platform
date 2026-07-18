#!/usr/bin/env python3
"""Isolated CPython 3.12 return-boundary leak probes for the proof module."""

from __future__ import annotations

import argparse
import dis
import gc
import importlib
import os
import sys
import tempfile
from pathlib import Path


class ReturnBoundaryError(RuntimeError):
    pass


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


def _run_probe(*, site: Path, scenario: str, loops: int) -> None:
    if sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 12):
        raise RuntimeError("native owner return-boundary proof requires CPython 3.12")
    sys.path.insert(0, str(site))
    module = importlib.import_module(
        "remote_runner._activation_release_dir_owner_proof"
    )
    required_hooks = {
        "_test_duplicate_directory",
        "_test_raise_sigint_after_adopt",
    }
    if not required_hooks <= set(dir(module)):
        raise RuntimeError("native owner proof module is missing test hooks")

    with tempfile.TemporaryDirectory(prefix="h2ometa-native-owner-boundary-") as raw:
        root = Path(raw) / "root"
        child = root / "child"
        root.mkdir(mode=0o700)
        child.mkdir(mode=0o700)
        raw_parent = os.open(
            root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
        )
        parent = module._test_duplicate_directory(raw_parent)
        os.close(raw_parent)
        child_status = child.stat()
        child_identity = (child_status.st_dev, child_status.st_ino)
        gc.collect()
        baseline = _fd_set()
        if _matching_fds(*child_identity):
            raise AssertionError("child descriptor exists before boundary probe")

        def acquire_child():
            child_owner = module._open_child(parent, "child")
            return child_owner

        store_offsets = {
            instruction.offset
            for instruction in dis.get_instructions(acquire_child)
            if instruction.opname == "STORE_FAST"
            and instruction.argval == "child_owner"
        }
        if len(store_offsets) != 1:
            raise AssertionError(f"unexpected STORE_FAST shape: {store_offsets}")
        store_offset = next(iter(store_offsets))

        def trace(frame, event, arg):
            del arg
            if event == "call" and frame.f_code is acquire_child.__code__:
                frame.f_trace = trace
                frame.f_trace_opcodes = True
                return trace
            if (
                event == "opcode"
                and frame.f_code is acquire_child.__code__
                and frame.f_lasti == store_offset
            ):
                raise ReturnBoundaryError("raised before STORE_FAST")
            return trace

        for _index in range(loops):
            if scenario == "sigint":
                module._test_raise_sigint_after_adopt(True)
                try:
                    leaked = acquire_child()
                except KeyboardInterrupt:
                    pass
                else:
                    module._close(leaked)
                    raise AssertionError("pending SIGINT did not interrupt the return")
                finally:
                    module._test_raise_sigint_after_adopt(False)
            elif scenario == "opcode":
                sys.settrace(trace)
                try:
                    leaked = acquire_child()
                except ReturnBoundaryError:
                    pass
                else:
                    module._close(leaked)
                    raise AssertionError("opcode trace did not interrupt STORE_FAST")
                finally:
                    sys.settrace(None)
            else:
                raise AssertionError(scenario)
            gc.collect()
            if _fd_set() != baseline:
                raise AssertionError("descriptor set changed across return boundary")
            if _matching_fds(*child_identity):
                raise AssertionError("child descriptor leaked across return boundary")
        module._close(parent)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--scenario", choices=("sigint", "opcode"), required=True)
    parser.add_argument("--loops", type=int, default=50)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.loops < 1:
        raise SystemExit("--loops must be positive")
    _run_probe(site=args.site, scenario=args.scenario, loops=args.loops)
    print(f"NATIVE_OWNER_BOUNDARY_OK scenario={args.scenario} loops={args.loops}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
