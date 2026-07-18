# H2OMeta activation release directory owner

This is a private, Linux x86-64-only proof project. It builds a CPython
3.12 Limited API extension that owns release-tree directory descriptors in a
private capsule. The production module exposes no raw descriptor, path-based
open, callback, replay, or fallback API.

The project is deliberately outside all remote-runner release source-copy
roots. CI builds production and proof-only wheels under `RUNNER_TEMP`. The
proof build has a separate private distribution, module name, and build entry
point. CI audits and imports both, runs kernel behavior tests against the
proof-only binary, and discards them. The production binary has no root seed
API, so this stage does not claim production-binary open/close behavior proof.
Neither wheel is a release artifact. Production adoption remains blocked on
root/session capability ownership, exact runtime and glibc qualification,
artifact hash/SBOM/provenance, versioning, archive import proof, and startup
preflight.

`Py_LIMITED_API` and an `abi3` filename cover only the CPython ABI. They do not
establish architecture, libc, kernel, filesystem, or behavioral portability.
