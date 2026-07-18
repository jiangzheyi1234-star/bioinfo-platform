# Deep Research: Capsule-only directory leaf primitives

Date: 2026-07-18
Status: decision input for a dormant Linux proof slice; not production enablement

## Executive summary

H2OMeta should not jump from the current directory-owner proof to a complete
release archive materializer. The smallest useful next slice is two fixed,
capsule-only directory operations:

```text
_mkdir_child(parent_directory_capsule, exact_component) -> directory_capsule
_fsync_directory(directory_capsule) -> None
```

`_mkdir_child` is create-only. It preallocates an empty owner before the first
namespace mutation, invokes Linux x86-64 `SYS_mkdirat` directly with mode
`0700`, refuses `EEXIST`, reopens the new child through the existing exact
`openat2` policy, adopts the descriptor before any Python handoff, applies and
reproves exact private mode, and reproves both parent and child identities.
Only the already accepted `openat2` `EAGAIN` case may be retried, for at most
three total identical calls (the initial call plus two retries). `mkdirat`,
`fchmod`, `fsync`, and `close` are not
retried after `EINTR` or any other error.

`_fsync_directory` remains a separate idempotent leaf: live proof, one `fsync`,
then post-proof. Keeping durability explicit avoids falsely presenting a
multi-syscall operation as atomic. A later journaled materializer can compose
child and parent syncs while assigning precise `outcome_unknown` semantics.
An exception between creation and sync may leave a markerless orphan, but it
cannot create authority: the current production extension has no root seed,
neither wheel is bundled, and this slice will not connect to startup,
publication, generation, archive replay, or a marker.

The main contrarian result is that exact mode is not exact metadata. Default
ACLs, xattrs, detached-but-live directory descriptors, same-UID mutation, and
filesystem or hardware durability remain outside this slice. Those gaps must
be closed by an ACL/xattr policy, a trusted-root fresh walk, versioned receipts,
marker-last publication, and exact production-mount acceptance before any
installed tree becomes authoritative.

## Research method

The repository was inspected from source commit
`5880b2e43c4385c84e69ed656b076c2814816f9f`. Firecrawl was run at the
exhaustive/no-limit tier across 16 search queries and returned 75 unique URLs.
Primary CPython, Linux kernel/man-pages, POSIX, OCI, SLSA, and libarchive sources
were preferred; exact CPython 3.12 and CPython 3.12.13 pages were then scraped
directly. Three read-only agents independently reviewed the repository boundary,
CPython ownership model, and Linux directory-relative operation semantics.

This report records the synthesis. Temporary
`.firecrawl/capsule-leaf-research/` collection output is ignored local evidence
and is not a release or source artifact.

## Current boundary

The repository already has four deliberately separate layers:

1. `activation_release_archive_inspection.py` owns an inspected regular archive
   file through `_io.FileIO` and exposes positional reads without returning its
   descriptor.
2. The archive graph and installed-tree contracts validate bounded topology,
   canonical hardlink primaries, exact link targets, modes, and fingerprints.
   They are logical evidence, not filesystem observation or authority.
3. `activation_release_materialization_io.py` proves a dormant Python
   `openat2` call shape but explicitly returns `raw_fd`; its own module contract
   forbids a production materializer from retaining that result.
4. `native/activation_fd_owner` provides a CPython 3.12 Limited API capsule that
   atomically adopts a directory descriptor opened by the exact `openat2`
   policy. The production binary has no root seed and has no runtime consumer.

The remaining gap is not “how to parse tar.” It is how to perform each
filesystem mutation through an owned capability without exposing a descriptor,
accepting or actively invoking an application callback, traversing a
caller-supplied path, or claiming durability or authority too early. The
documented CPython signal-dispatch point remains an explicit exception.

## Decision

### Accepted production-shaped surface

The next native wheel version will expose exactly these five production
methods:

```text
_open_child
_mkdir_child
_fsync_directory
_require_live
_close
```

It will continue to expose no root seed, raw descriptor, `fileno`, borrow/take
operation, path opener, callback parameter, active application-callback API,
iterator, replay operation, fallback, unlink, rename, link, symlink, marker, or
archive consumer. Proof hooks remain in the
separately named proof distribution and module only.

The surface change requires a private wheel version change from `0.1.0` to
`0.1.1`; production and proof distribution names, module names, `PyInit_*`
symbols, and capsule names remain distinct. Both wheels continue to be built
under `RUNNER_TEMP`, validated, imported, tested, and discarded.

### `_mkdir_child` contract

The fixed sequence is:

1. Parse an exact directory capsule and exact `str` component while holding the
   GIL. Reuse the existing printable-ASCII, one-component, reserved-prefix
   validator.
2. Reprove the parent descriptor identity and private directory policy.
3. Allocate the child owner and `PyCapsule` with `fd = -1` before mutation.
4. Invoke `syscall(SYS_mkdirat, parent_fd, component, 0700)` exactly once.
   Direct invocation is a closed-binary, statically auditable no-fallback
   policy: an accepted `openat2` kernel is already much newer than the kernel
   that needs glibc's documented `/proc/self/fd` fallback. The source must fail
   compilation when `SYS_mkdirat` is absent and statically assert Linux x86-64
   syscall number 258. `EEXIST`, including an existing file, directory, or
   symlink, is a conflict and never means “adopt it.”
5. Reopen the component with the existing
   `O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC` and
   `RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS |
   RESOLVE_NO_XDEV` shape. Only `EAGAIN` receives the existing bounded,
   identical retry.
6. Store the returned descriptor in the preallocated owner immediately, before
   any further operation that can fail.
7. Apply `fchmod(fd, 0700)`, then verify directory type, exact mode, same UID,
   same device as the parent, stable device/inode, and `FD_CLOEXEC`.
8. Once `mkdirat` has been issued, every failure exit first saves the original
   result and reproves the parent. After descriptor adoption it also reproves
   the child; an identity failure takes precedence over the original syscall
   error. The successful exit performs the same parent and child reproof.

The operation does not call `fsync`. A successful namespace mutation followed
by any later failure may leave a private, markerless directory. That directory
is abandoned evidence only. A higher layer must never delete and reuse the same
opaque publication identity or silently reopen it as a successful retry.

### `_fsync_directory` contract

The fixed sequence is:

1. Parse and reprove one live directory capsule.
2. Invoke `fsync(fd)` exactly once without releasing the GIL or accepting or
   actively invoking an application callback.
3. Save the syscall result and `errno`, then reprove the same capsule.
4. If post-proof fails, surface the identity failure. Otherwise surface the
   original `fsync` result.

There is no `EINTR` retry and no success downgrade. A directory filesystem that
does not support the required sync behavior fails mount acceptance. Syncing a
child directory does not make its entry in the parent durable; future
orchestration must sync mutated directories bottom-up and sync the containing
parent explicitly.

### Why the two methods stay separate

A single `_mkdir_child_durable` operation was considered. It could create,
adopt, chmod, sync the child, and sync the parent before returning. It would
reduce the Python interleaving window, but it would not be atomic: any error
after `mkdirat` still leaves a namespace object, and a parent-sync failure still
requires fresh-session reconciliation. Naming the result “durable” would invite
callers to overread a multi-syscall sequence as an authority transition.

Two leaves make the evidence and error boundary explicit. The resource handoff
that cannot be safely expressed in Python remains inside `_mkdir_child`; the
idempotent durability operation is separately testable and composable. A later
native orchestration operation remains possible if the journal design proves
that reducing cancellation points is worth the larger semantic unit.

## CPython ownership constraints

CPython 3.12 documents that a capsule pointer cannot be `NULL`, a non-null name
must outlive the capsule, and a destructor is called when the capsule is
destroyed. The name therefore remains a static string and the owner allocation
continues to use the matching `PyMem_Malloc`/`PyMem_Free` family. Every failure
after capsule allocation decrements that capsule, allowing the single
destructor to consume a live descriptor or safely observe `fd = -1`.
If `PyCapsule_New` itself fails, the capsule never owns the allocation, so the
caller frees the owner directly. Only a successfully created capsule transfers
cleanup responsibility to the destructor.

The component UTF-8 buffer is owned by an exact Unicode object while the
method's argument tuple remains live and the GIL remains held. It is never
stored past the call. The implementation does not use `Py_BEGIN_ALLOW_THREADS`,
buffer callbacks, or an application callable. If a
future regular-file primitive accepts bytes, it must either hold an immutable
exact `bytes` object for the whole syscall loop or acquire/release a
`Py_buffer` on every failure path; the current directory slice needs neither.

The implementation does not explicitly call `PyErr_CheckSignals`, but
`PyErr_SetFromErrno(EINTR)` does so internally and may run the Python signal
handler. Before errno conversion, every acquired descriptor must therefore be
owned by a capsule (or reset to `-1`), and every saved syscall/namespace state
must be internally consistent. This is a permitted signal-dispatch point, not
an application callback API.

CPython signals are handled on the main thread of the main interpreter at
Python execution checkpoints, and `sys.monitoring.INSTRUCTION` fires before
the target bytecode.

The existing CPython 3.12 return-boundary proof therefore remains relevant:
when an exception is injected before `STORE_FAST`, the returned capsule stays on
the value stack and frame unwind decrefs it. The new `_mkdir_child` path must be
added to that proof; the created directory may remain, but its descriptor must
not leak.

`Py_LIMITED_API` and an `abi3` filename declare and target a CPython ABI claim;
the filename does not validate conformance. CPython's own documentation warns
that the macro does not prove semantics and that
platform ABI includes OS, architecture, compiler, and lower libraries. Linux
x86-64, libc, kernel, filesystem, and behavior qualification remain separate.

## Linux filesystem constraints

`mkdirat` resolves a relative component from a directory descriptor, but mode
is affected by umask, default ACLs, and parent setgid behavior. The exact
post-open `fchmod` and `fstat` checks close the ordinary mode ambiguity; they do
not remove named ACL entries or unrelated xattrs. Authority must wait for a
fresh-walk policy that rejects or normalizes those metadata classes.

The current `openat2` flags remain intentionally strict. `O_NOFOLLOW` alone
protects only the final component, while `RESOLVE_NO_SYMLINKS` covers every
component and `RESOLVE_NO_XDEV` also rejects bind mounts. This can reject some
legitimate operator layouts. It is an accepted fail-loud compatibility cut, not
a silent fallback candidate.

`fsync` on an object does not by itself make the containing directory entry
durable. Conversely, `close` is not a durability barrier. Linux releases a file
descriptor early during close processing, so retrying a failed `close` can
close a reused descriptor. POSIX.1-2024 selected a different `EINTR` model than
current Linux; this project therefore makes a Linux-specific single-close
claim and does not present it as portable POSIX behavior.

A retained directory descriptor remains attached to the inode after rename or
detachment. Capsule identity is therefore not final pathname binding. Before a
marker can authorize execution, a future publisher must reopen from the trusted
root, compare device/inode and full metadata, complete a fresh tree walk, and
bind that observation into a versioned receipt.

## Deferred primitives

Regular files require a distinct file-capsule identity and a bounded partial
write state machine. The future order is create-only `openat2`, immediate
adoption, write-all with explicit offset, relocation evidence where required,
fixed `fchmod`, `fsync(file)`, and `fsync(parent)`. No raw fd or Python iterator
may cross the owner boundary.

Hardlinks require the already canonicalized primary path plus a trusted primary
inode binding. `linkat(..., flags=0)` must be destination-create-only, followed
by exact device/inode, alias-group, and link-count proof. Symlinks come last;
`symlinkat` does not validate its target, so it may consume only an exact target
from the fully validated projection, followed by `readlinkat` reproof and parent
sync. A failed post-link proof can itself leave a namespace orphan; it must enter
journaled abandoned reconciliation, never best-effort name cleanup. Neither link
type belongs in this directory-only slice.

## Rejected alternatives

- Complete materializer now: rejected because it combines regular-file
  streaming, relocation, link graph replay, sealing, receipt, marker, and crash
  recovery before the directory mutation boundary is proved.
- Python raw-fd bridge: rejected because a signal exception can occur after a
  syscall returns and before Python stores an owner.
- `openat` or path-check fallback: rejected because final-component
  `O_NOFOLLOW` is not the accepted dynamic-descendant policy.
- Libc `mkdirat` wrapper: rejected for this Linux x86-64 proof because the
  documented old-kernel fallback constructs `/proc/self/fd` paths. A direct
  syscall makes “no path fallback” statically auditable.
- Auto-adopt on `EEXIST`: rejected because it aliases a prior or competing
  object and converts an unknown outcome into false idempotency.
- Best-effort cleanup after an ambiguous mutation: rejected because deleting by
  name can remove a replaced object and enables unsafe opaque-ID reuse.
- File, hardlink, symlink, rename, or marker methods in this slice: rejected to
  keep the primitive boundary independently reviewable and non-authoritative.

## Proof and staged delivery plan

1. Refactor the 785-line C source into owner/core, module, and directory-leaf
   sources, each under 800 lines. Preserve the `0.1.0` behavior exactly, build
   both wheels, and push this mechanical commit first.
2. Add `_mkdir_child` and `_fsync_directory`, bump both private wheels to
   `0.1.1`, update the validator, and include all syscall, mode, identity,
   ownership, error, return-boundary, and no-consumer tests in the same behavior
   commit. Keep production and proof identities separate.
   A proof-only capsule-creation failure after owner allocation and before
   mutation must exercise the real pre-transfer cleanup label and prove
   `MemoryError`/`NULL`, balanced owner allocation/free, zero destructor calls,
   and zero namespace mutation. Static source-order checks remain required.
3. Run Windows import-safe contract/validator checks, then the required Ubuntu
   build and functional matrix on standard-GIL CPython 3.12, 3.13, and 3.14.
   Every minor runs ownership, error cleanup, real/injected filesystem behavior,
   SIGINT, and `sys.monitoring.INSTRUCTION` return-boundary coverage; import-only
   is not behavior support. Every minor also runs proof-only pending `SIGINT` +
   injected `EINTR` at errno conversion, proving no retry, handler-exception
   precedence, consistent owner/fd/namespace state before dispatch, no fd leak,
   and markerless-abandoned handling after mutation.
4. After the required native job succeeds, make an evidence-only commit with
   exact source SHA, runner image, Python versions, wheel identities,
   validator/abi3audit results, and test count. Record the parent workflow's
   actual conclusion and do not infer whole-CI or branch acceptance. This commit
   must not change native source, tests, or contracts; it only records evidence
   for the exact behavior-commit SHA.

Required test cases include exact surface, preallocation before mutation,
direct `SYS_mkdirat`, single-attempt mutation errors, `EEXIST` for file/
directory/symlink, exact component policy, exact `0700`, UID/device/CLOEXEC,
parent and child reproof, bounded `openat2` `EAGAIN`, single-attempt `fsync`,
post-proof precedence, descriptor reuse, destructor cleanup, SIGINT/opcode
return-boundary cleanup, pre-transfer capsule-creation failure, in-method
pending-signal `EINTR` dispatch, every source file under 800 lines, and no
runtime consumer.

## Contrarian views and risks

- Mode-only proof can miss default ACLs, named ACL entries, security
  capabilities, SELinux labels, and other xattrs.
- Same-UID and root mutation remain outside the local threat model. A private
  directory and global lifecycle gate coordinate trusted processes; they are
  not mandatory access control.
- Consequently, binding the inode reopened after `mkdirat` to the name just
  created is claimed only within the current model that excludes same-UID/root
  replacement, not as an adversarial namespace proof.
- `RESOLVE_NO_XDEV` rejects bind mounts that some operators may consider valid.
  Supporting them would require a different, explicitly versioned policy and
  evidence profile.
- Directory `fsync` behavior and hardware cache truth vary. CI syscall success
  is not a power-loss proof.
- A namespace mutation can outlive a failed call. Without an external journal,
  “retry” and “cleanup” are unsafe words; only a new opaque identity is safe.
- Resource exhaustion after namespace creation can leave many private orphans.
  A future journal needs quotas and audited reclamation that never reuses IDs.
- The production capsule still lacks a root/session authority chain. Adding
  leaves does not make the module reachable or releasable.
- A fresh inode proof still does not prove relocation correctness or complete
  installed-tree content. Receipt and marker work remains independent.

## Open questions

- Will the first supported production profile reject all ACLs and xattrs, or
  normalize a narrow allowlist and include it in tree identity?
- Which exact ext4/XFS mount options and storage hardware define the first
  directory-`fsync` acceptance profile?
- Should a later journaled materializer compose the two leaves from Python or
  add a larger native orchestration operation to reduce cancellation points?
- What evidence schema distinguishes create conflict, markerless abandoned,
  sync failure, identity drift, and final outcome unknown?
- How will trusted-root fresh reopen prove that a retained inode is still bound
  to the intended opaque final pathname?
- When regular files arrive, is a fixed-size bytes-chunk API sufficient, or is
  a native archive reader required to avoid Python callback and cancellation
  boundaries during partial writes?

## Sources

- [CPython 3.12 capsules](https://docs.python.org/3.12/c-api/capsule.html) — pointer, name lifetime, destructor, and Stable ABI semantics.
- [CPython 3.12 argument parsing](https://docs.python.org/3.12/c-api/arg.html) — borrowed buffers, `Py_buffer`, and cleanup obligations.
- [CPython 3.12 Unicode objects](https://docs.python.org/3.12/c-api/unicode.html#c.PyUnicode_AsUTF8AndSize) — cached UTF-8 buffer ownership and lifetime.
- [CPython 3.12 exception handling](https://docs.python.org/3.12/c-api/exceptions.html) — error indicator and resource cleanup rules.
- [CPython 3.12 memory management](https://docs.python.org/3.12/c-api/memory.html) — allocator-family ownership.
- [CPython 3.12 C API stability](https://docs.python.org/3.12/c-api/stable.html) — Limited API, Stable ABI, semantic and platform caveats.
- [PEP 652](https://peps.python.org/pep-0652/) — Stable ABI maintenance process.
- [CPython 3.12 `sys.monitoring`](https://docs.python.org/3.12/library/sys.monitoring.html) — instruction-before-execution event semantics.
- [CPython 3.12 signal handling](https://docs.python.org/3.12/library/signal.html) — main-thread handler and arbitrary-bytecode exception boundary.
- [CPython 3.12.13 capsule implementation](https://github.com/python/cpython/blob/v3.12.13/Objects/capsule.c) — concrete destructor/deallocation implementation.
- [CPython 3.12.13 bytecode implementation](https://github.com/python/cpython/blob/v3.12.13/Python/bytecodes.c) — monitoring failure and frame unwind evidence.
- [Linux `mkdirat(2)`](https://man7.org/linux/man-pages/man2/mkdir.2.html) — dirfd resolution, mode, `EEXIST`, and glibc fallback caveat.
- [Linux `open/openat(2)`](https://man7.org/linux/man-pages/man2/open.2.html) — open file descriptions, dirfd stability, and `O_NOFOLLOW` scope.
- [Linux `openat2(2)`](https://man7.org/linux/man-pages/man2/openat2.2.html) — exact resolve flags and `EAGAIN` semantics.
- [Linux pathname resolution](https://man7.org/linux/man-pages/man7/path_resolution.7.html) — component traversal semantics.
- [Linux kernel pathname lookup](https://docs.kernel.org/filesystems/path-lookup.html) — kernel lookup, symlink, mount, and magic-link behavior.
- [Linux `fchmod(2)`](https://man7.org/linux/man-pages/man2/chmod.2.html) — descriptor-relative mode mutation and postcheck need.
- [Linux `fstat(2)`](https://man7.org/linux/man-pages/man2/stat.2.html) — descriptor identity and metadata observation.
- [Linux `fsync(2)`](https://man7.org/linux/man-pages/man2/fsync.2.html) — data/metadata sync and containing-directory boundary.
- [Linux `close(2)`](https://man7.org/linux/man-pages/man2/close.2.html) — early descriptor release, no retry, and no durability guarantee.
- [POSIX.1-2024 `close`](https://pubs.opengroup.org/onlinepubs/9799919799/functions/close.html) — portable `EINTR` model contrasted with Linux.
- [Linux `write(2)`](https://man7.org/linux/man-pages/man2/write.2.html) — partial-write and delayed-error requirements for the deferred file capsule.
- [Linux `linkat(2)`](https://man7.org/linux/man-pages/man2/link.2.html) — no-replace hardlink and cross-filesystem semantics.
- [Linux `symlinkat(2)`](https://man7.org/linux/man-pages/man2/symlink.2.html) — unchecked target and destination creation semantics.
- [Linux `renameat2(2)`](https://man7.org/linux/man-pages/man2/rename.2.html) — deferred no-replace publication boundary.
- [POSIX `openat`](https://pubs.opengroup.org/onlinepubs/9799919799/functions/open.html) — race-resistant directory-relative intent.
- [POSIX `linkat`](https://pubs.opengroup.org/onlinepubs/9699919799/functions/link.html) — directory-relative link intent.
- [Linux ACLs](https://man7.org/linux/man-pages/man5/acl.5.html) — default ACL inheritance and mode interaction.
- [Linux xattrs](https://man7.org/linux/man-pages/man7/xattr.7.html) — metadata outside ordinary mode bits.
- [libarchive secure extraction flags](https://manpages.debian.org/unstable/libarchive-dev/archive_write_disk.3.en.html) — comparison point for symlink and `..` policies.
- [libarchive hardlink boundary report](https://github.com/libarchive/libarchive/issues/746) — contrarian evidence for validating link targets before extraction.
- [OCI image layer specification](https://github.com/opencontainers/image-spec/blob/main/layer.md) — filesystem changeset and link representation comparison.
- [SLSA build provenance](https://slsa.dev/spec/v1.2/build-provenance) — provenance fields for a future native artifact.
- [SLSA build requirements](https://slsa.dev/spec/v1.2/build-requirements) — controlled builder requirements.

## Rerun inputs

```text
workflow: firecrawl-deep-research
topic: CPython 3.12 abi3 capsule-only directory leaf primitives for a Linux fd-relative release-tree materializer, with no raw descriptors, callbacks, fallback, or production wiring
depth: exhaustive (no time limit)
output: markdown decision report
```
