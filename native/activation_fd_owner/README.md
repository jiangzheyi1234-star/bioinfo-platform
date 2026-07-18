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
API, so dynamic filesystem behavior remains proof-binary evidence rather than
production wiring.
Neither wheel is a release artifact. Production adoption remains blocked on
root/session capability ownership, exact runtime and glibc qualification,
artifact hash/SBOM/provenance, versioning, archive import proof, and startup
preflight.

`Py_LIMITED_API` and an `abi3` filename cover only the CPython ABI. They do not
establish architecture, libc, kernel, filesystem, or behavioral portability.

## Required-platform evidence

GitHub Actions
[run 29634613659](https://github.com/jiangzheyi1234-star/bioinfo-platform/actions/runs/29634613659),
[job `python / native-activation-fd-owner-linux`](https://github.com/jiangzheyi1234-star/bioinfo-platform/actions/runs/29634613659/job/88054632583),
concluded `success` for source
`c5d7135fbac8ec7e0cbd5ee1d00c94e3c201e7c0` on Ubuntu 24.04 x86-64 runner
image `20260714.240.1`. The job built, validated, and strictly audited the
production and proof `0.1.1` `cp312-abi3-linux_x86_64` wheels. It imported
their exact surfaces and ran the complete 64-test behavior suite on each of
standard-GIL CPython 3.12.13, 3.13.14, and 3.14.6; 29 static contract and wheel
checks also passed. The parent workflow concluded `failure` because separate
governance and Windows jobs failed, so this is isolated native-job
evidence, not whole-CI or branch acceptance. See the
[exact evidence record](../../docs/research/2026-07-18-capsule-only-directory-leaf-evidence.md).
