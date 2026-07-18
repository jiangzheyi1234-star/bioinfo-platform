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

## Required-platform evidence

GitHub Actions
[run 29630042088](https://github.com/jiangzheyi1234-star/bioinfo-platform/actions/runs/29630042088),
[job `python / native-activation-fd-owner-linux`](https://github.com/jiangzheyi1234-star/bioinfo-platform/actions/runs/29630042088/job/88041786548),
concluded `success` for source
`8722fec795baadf72b9d024d442d041213f609c4` on Ubuntu 24.04 x86-64 runner
image `20260714.240.1`. The job built and audited the production and proof
`cp312-abi3-linux_x86_64` wheels, imported both on CPython 3.12.13 and 3.13.14,
and completed the combined contract, wheel-validator, and proof-only Linux
behavior suite with 51 passed. The parent workflow run concluded `failure`, so
this is isolated job evidence, not whole-CI or branch acceptance.
