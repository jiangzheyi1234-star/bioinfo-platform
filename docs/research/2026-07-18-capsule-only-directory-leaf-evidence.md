# Required Linux evidence: capsule-only directory leaves 0.1.1

Date: 2026-07-18

Status: required native proof succeeded for the exact behavior commit; dormant
proof only, not whole-CI or production enablement

## Exact subject

- Branch: `codex/remove-first-run-wizard`
- Behavior commit:
  `c5d7135fbac8ec7e0cbd5ee1d00c94e3c201e7c0`
- Commit subject: `feat(runner): add capsule-only directory leaves`
- Production surface: `_open_child`, `_mkdir_child`, `_fsync_directory`,
  `_require_live`, `_close`
- Production root seed or runtime consumer: none

The evidence below applies only to that exact source SHA. The evidence-only
commit that contains this record does not change native source, tests,
contracts, build configuration, or CI behavior.

## Required job result

GitHub Actions
[run 29634613659](https://github.com/jiangzheyi1234-star/bioinfo-platform/actions/runs/29634613659)
used the exact behavior commit above. Its required isolated
[job `python / native-activation-fd-owner-linux`](https://github.com/jiangzheyi1234-star/bioinfo-platform/actions/runs/29634613659/job/88054632583)
completed successfully.

The job ran on:

- runner version `2.335.1`;
- runner image `ubuntu-24.04`, version `20260714.240.1`;
- image provisioner version `20260707.563`;
- Linux x86-64.

The job built and then discarded exactly these private wheels under
`RUNNER_TEMP`:

```text
h2ometa_activation_release_dir_owner-0.1.1-cp312-abi3-linux_x86_64.whl
h2ometa_activation_release_dir_owner_proof-0.1.1-cp312-abi3-linux_x86_64.whl
```

Both builds compiled the same ordered source set: owner/core, directory leaf,
then module. Production and proof retained separate distribution, module,
`PyInit_*`, capsule, and method identities. The escape scan found no wheel,
shared object, object file, build directory, distribution directory, or
egg-info output under the repository runtime/source roots.

## ABI and interpreter matrix

The wheels were built with standard-GIL CPython `3.12.13`. The validator
accepted both wheel identities and imported their exact method surfaces on:

```text
CPython 3.12.13
CPython 3.13.14
CPython 3.14.6
```

The workflow asserted the exact minor and rejected `Py_GIL_DISABLED` before
validation. `abi3audit==0.0.26` ran with `--strict` against both wheels and the
job remained successful. This proves the tested CPython ABI/import boundary;
it does not prove portability across architecture, libc, kernel, filesystem,
mount policy, or free-threaded CPython.

## Test evidence

The locked project environment ran the static contract and wheel-validator
slice once:

```text
29 passed
```

It then ran the complete native behavior suite independently on each of the
three standard-GIL interpreters:

```text
CPython 3.12.13: 64 passed
CPython 3.13.14: 64 passed
CPython 3.14.6:  64 passed
```

The behavior matrix included create-only `SYS_mkdirat`, three `EEXIST`
shapes, exact `0700`, UID/device/CLOEXEC and stable identity, bounded identical
`openat2` `EAGAIN`, markerless orphan handling, single-attempt
`mkdirat`/`fchmod`/`fsync`/`close`, parent/child reproof and deterministic error
precedence, capsule pre-transfer cleanup, descriptor destruction/reuse, and
closed-capability rejection.

Every minor also ran both operations through pending-SIGINT and
`sys.monitoring.INSTRUCTION` return-boundary probes. Separate in-method probes
covered injected `EINTR` at `mkdirat`, `openat2`, `fchmod`, and `fsync` errno
conversion, including handler-exception precedence, no retry, state consistency
before dispatch, and no descriptor leak. A real issued `mkdirat` that returns
`EINTR` remains outcome-unknown; proof injection skips the syscall and may
claim known-no-mutation only for that injected case.

Before push, the Windows import-safe slice also completed with Ruff and format
checks green, `43 passed`, and `64 skipped` Linux-only cases.

## Parent workflow result

The parent workflow concluded `failure`; this record therefore does not claim
whole-CI or branch acceptance.

- `security / governance` failed the Python dependency audit because locked
  `click 8.3.2` matched `PYSEC-2026-2132`; the reported fixed version is
  `8.3.3`.
- `python / windows` reported `33 failed, 4496 passed, 185 skipped`. No failing
  test belonged to the native-owner slice; the logged set included source-size
  and route/UI contract drift plus Python tests that expected
  `apps/web/node_modules/typescript`, which that job does not install.
- The native job, Linux activation-storage job, Linux parity job, Windows web
  job, and whitespace job completed successfully.
- `required / ci-green` failed because required parent jobs were not all green.

Those separate failures need their own scoped remediation. They neither erase
the isolated native result nor permit it to be described as full acceptance.

## Result and remaining boundary

The `0.1.1` directory-leaf behavior commit satisfies the accepted dormant proof
gate. It does not authorize bundling, upload, startup wiring, production root
seeding, archive materialization, cleanup/reuse of markerless orphans, or a
durability/authority claim. Regular-file, hardlink, symlink, receipt, marker,
fresh trusted-root walk, ACL/xattr policy, journaled reconciliation, provenance,
and production mount/runtime acceptance remain deferred.
