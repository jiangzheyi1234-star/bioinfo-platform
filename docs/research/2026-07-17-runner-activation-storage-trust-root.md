# Runner activation storage trust-root research

Date: 2026-07-17
Status: decision input for the dormant Agent-first activation control plane

## Executive summary

Generation publication remains unsafe. The runner first needed an immutable
two-name enrollment phase promotion that binds one canonical `runnerRoot` to
one installation record, plus a session that continuously reproves every
retained child file descriptor against its canonical pathname. With that trust
root defined, the next accepted dormant slices are installed release-tree
publication and versioned config-integrity key storage; they may progress in
parallel, but neither may be mistaken for generation readiness on its own.

Without those two properties, a caller can present a different installation ID
for the same root, or a same-UID process can rename a child tree while an old
session continues reading and writing detached authority. Persisting key
material on top of that boundary would only make the ambiguity durable.

The accepted dependency order is:

```text
installation intent/final enrollment + complete child capability proof
        ├── installed release-tree identity
        └── versioned config-integrity key storage
                  ↓
verified immutable generation publisher
                  ↓
transition and invocation journals
                  ↓
protocol v6 startup and lifecycle mutation wiring
```

Installed-tree identity and key storage are parallel logical dependencies after
the trust root. A publisher may still choose the deterministic operational
order "tree first, then key" so a durable key never authorizes an absent tree.
Neither dependency may be replaced by an archive hash or a self-consistent
caller-supplied descriptor.

## Research method

This review used more than a dozen discovery queries and dozens of primary or
upstream sources through Firecrawl. Source classes were Linux man-pages, Linux
kernel documentation, Python documentation and PEPs, systemd upstream design,
NIST publications, RFCs, and supply-chain specifications from TUF, in-toto,
OCI, and SLSA. Product blogs and secondary summaries were excluded from the
decision basis.

The searches covered `open`/`openat2`, `renameat2(RENAME_NOREPLACE)`, `fsync`,
`write`, `close`, `stat`, `flock`, mount identity, ext4/XFS/OverlayFS,
`getrandom`, Python secret generation and comparison, systemd credentials,
HKDF/SP 800-108, archive extraction, and installed-tree identity.

## Findings and decisions

### 1. Two-phase enrollment must precede secret persistence

The installation contract already has canonical JSON and a domain-separated
fingerprint, but until now the Linux storage session trusted only the record
passed by its caller. The same filesystem root could therefore be opened under
another installation ID while using the same lock and journal.

The accepted remote enrollment uses two fixed, non-secret files directly under
the stable `shared` directory:

```text
shared/installation-enrollment-intent.json  # mutually exclusive phase names
shared/installation-enrollment.json
```

The active file's bytes are exactly the existing installation-v1 canonical
JSON plus one LF, as a current-UID regular file with mode `0600`, link count
one, and the shared filesystem's device identity. Intent and final are phases
of the same inode: they never coexist in a valid state.

The required state machine is:

1. Reprove canonical `runnerRoot -> shared`, then create or open the stable
   `shared/global-activation.lock` and hold it before authoritative phase
   classification or any record/layout mutation. The missing-gate creation
   guard may only test whether phase/activation names exist. The lock name is
   never removed or promoted, closing stale virgin-check ABA races.
2. Under that gate, valid phases are only virgin (neither record and no
   activation tree), recoverable (intent only), or authoritative (final only).
   Both records, or neither record with an activation tree, fail closed.
3. In virgin state, publish the intent with a no-replace CAS before creating
   any activation directory. This selects the only installation identity that
   may initialize the root.
4. An exact intent authorizes that same installation to create or reconcile
   the fixed activation skeleton after a crash. It does not authorize a
   different identity or adoption of unknown descendants.
5. Prove the complete root/shared/gate/activation/staging/journal pathname-to-fd
   chain and exact empty pre-final skeleton. Then atomically promote the intent
   inode to the final name with `renameat2(RENAME_NOREPLACE)`, fsync `shared`,
   prove the final inode is unchanged and intent is absent, and reprove the
   empty skeleton and layout. Unknown entries, registrations, or staging
   orphans are never adopted.
6. In final-only state, missing activation children or the stable global lock
   are integrity failures and are never recreated automatically.

The initial intent uses a random same-directory `0600` staging entry inside a
trusted `shared` base that is not group/world writable. Promotion moves that
already-verified inode and creates no second payload file. This trusted-base
rule is not a relaxation for later secret storage, which still requires
private `0700` directories.

The intent/final phase proves only local-root bootstrap authority. Copying the
tree copies that phase, so it does not prove a physical machine, SSH host
identity, or activation `prepared` evidence. Before production enablement,
controller-side trust must separately bind the installation fingerprint to an
explicitly trusted SSH host-key fingerprint, endpoint, and audited enrollment
event.

### 2. Directory descriptors must be rebound to canonical names

`O_NOFOLLOW` applies to the final component of an `open` operation, not to an
entire previously traversed tree. Retaining a descriptor protects access to its
inode, but after a rename it may be a detached inode rather than the canonical
entry.

Every authoritative session check must therefore compare descriptor and
nofollow pathname `st_dev/st_ino` for:

```text
runnerRoot -> shared
shared -> global-activation.lock
shared -> activation
activation -> activation/.staging
activation -> generation-registrations
generation-registrations -> .staging
```

It must also recheck type, owner, mode, device, filesystem magic, and the
canonical root before and after the child-chain proof. Bootstrap/recovery
requires intent-only, while every authoritative open requires intent absent
and final exact, followed by a second layout proof. Authoritative journal reads
repeat this before and after reading, even
when parsing reports a conflict, so a detached tree is reported as unavailable
rather than mislabeled as canonical corruption.

For future dynamic descendant paths, Linux `openat2` with
`RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS |
RESOLVE_NO_XDEV` is the preferred stronger primitive. The pinned Python runtime
does not expose a documented high-level `openat2` API, so any use requires a
narrow native/syscall helper and explicit kernel/ABI acceptance; there is no
path-check fallback.

### 3. Durable no-replace publication has a strict state machine

The accepted publication sequence is:

1. Create an unpredictable staging entry with
   `O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC` and mode `0600`.
2. Reapply and validate mode, type, owner, link count, size, and device.
3. Loop `write` until all bytes are written.
4. `fsync` the file and staging directory.
5. Publish on the same filesystem with `renameat2(RENAME_NOREPLACE)`.
6. `fsync` both source and destination directories.
7. Nofollow-reopen the final entry, compare its inode and metadata, and reread
   exact bytes.

For ordinary staging publication, an `EEXIST` result is successful only after
exact secure reread. For intent-to-final promotion, `EEXIST` means the invalid
both-name state and is a conflict. A known failure before rename is not
published. An unexpected rename result, or any failure
after rename may have committed, is `outcome_unknown` and must be reconciled in
a fresh session that reacquires the global gate once the fixed activation
skeleton is available. A final file is never deleted in the unknown class.

File `fsync` does not make a containing directory entry durable, successful
`write` may be partial, and successful `close` is not a durability proof.
Delayed I/O errors may surface during `fsync` or `close`; retrying `close` is
unsafe because the descriptor number may already have been reused.

The first implementation continues to allow only directly mounted ext4 and
XFS with matching mountinfo device and `fstatfs` magic. NFS rename errors can be
ambiguous, while OverlayFS copy-up and inode behavior weaken the intended
identity proof. There is no portable fallback.

### 4. Key storage is an accepted separate dormant dependency

After enrollment, the dormant key-store implementation uses the same global gate and
no-replace protocol, but does not enlarge the enrollment skeleton or the set of
file descriptors retained by `ActivationStorageSession`. Each key operation
reproves the canonical session and dynamically opens or creates this exact
private scope:

```text
activation/secrets/config-integrity/
  .staging/<configBlobIntegrityKeyId>.pending
  <configBlobIntegrityKeyId>.key
```

All three directories are current-UID, same-device, exact `0700` directories.
The deterministic pending name permits a fresh process to classify a crashed
publication without scanning or adopting arbitrary files. Pending and final
are current-UID regular files with exact mode `0600`, link count one, the same
device, and exactly 32 raw bytes. Every fixed path it consumes rejects an
unexpected name, type, link count, length, owner, mode, or device.

Create-or-verify receives explicit material; it does not generate, rotate,
prune, import, or export a key. A read with no final, or reconciliation with
neither an exact final nor an exact pending entry, returns typed `absent`
instead of generating material or collapsing absence into a generic backend
error. Exact retries first prove fixed length and then use
`hmac.compare_digest`; a different payload for the same key ID is a permanent
conflict. Observations expose only non-secret fingerprints and dispositions,
not material, paths, raw IDs, or tags.

Any ambiguous rename result, or any durability/reproof failure after rename is
`outcome_unknown`. Reconciliation must close the old capabilities and start a
fresh storage session that reacquires the global gate, reproves the canonical
root/layout, and classifies the deterministic pending and final entries. It
must never infer success or absence from the previous exception or detached
file descriptors. This store remains disconnected from protocol v5,
bootstrap, rotation, generation publication, transitions, and `prepared`.
The implementation is therefore a dormant dependency, not a production-wired
credential backend or generation-readiness claim.

When an authorized caller creates new material, it should come from
`secrets.token_bytes(32)`/the OS CSPRNG. On
Linux, Python's `os.urandom` uses blocking `getrandom` semantics so it does not
return weak early-boot entropy. `GRND_RANDOM` is unnecessary.

Python cannot promise complete memory erasure: immutable `bytes`, allocator
arenas, hash/HMAC temporaries, stack, and register copies may remain. Mutable
buffers may be overwritten as best effort, but a verified erasure requirement
needs a native isolated component, TPM/HSM, KMS, or another custody boundary.

Likewise, private modes and nofollow proof do not defend against root or a
malicious process with the same UID; that process can read or mutate the same
namespace. Stronger custody requires a separately constrained service UID or
an external credential boundary, not a stronger claim about `0600`.

Windows tests may cover canonical orchestration, error taxonomy, and the fault
state machine, but they are not Linux syscall evidence. The Ubuntu job must be
non-skippable and cover dynamic directory creation/reopen, owner/mode/link/
device checks, deterministic pending recovery, no-replace publication,
file/directory `fsync`, typed `absent`, and fresh-session reconciliation after
every ambiguous crash boundary.

For derived keys, use HKDF-SHA-256 or NIST SP 800-108r1 with versioned,
unambiguous domain separation that includes purpose, installation, generation,
and installed-tree identity. HMAC authenticates data; it does not encrypt it or
protect against an attacker who can read the same root key.

### 5. Archive digest is not installed-tree identity

An archive, OCI descriptor, or TUF target hash identifies downloaded blob
bytes. Extraction policies can reject or rewrite paths, links, modes, owners,
and special files, and Python's tar defaults have changed across versions.
Therefore the archive hash cannot authorize the executable tree.

The release publisher must pin an extraction policy and construct a canonical
manifest from a nofollow walk. The manifest needs schema and extraction-policy
versions plus normalized relative name, type, mode, size, content digest, and
an explicitly allowed link target where applicable. Unicode/path-byte rules,
hardlinks, symlinks, and special files must be closed by schema. Only after the
tree and manifest are durable and no-replace published may a generation bind
the tree digest.

The dormant v1 contract resolves its portable name policy to canonical
printable-ASCII relative POSIX paths and keeps two domain-separated identities:
one for the ordered tree content and one for the complete manifest. It models
read-only directories/files, relative symlinks, and internal hardlinks
explicitly; archive digest, installation/path, source, platform, provenance,
and publication disposition remain separate future receipt evidence. This
matches the separation in OCI descriptors and in-toto/SLSA subjects: those
formats can bind a distributed object and its provenance, but they do not prove
the bytes produced by local extraction. TUF can add signed target length/hash,
version, and expiry policy, but likewise does not replace installed-tree
verification. Nix and OSTree are useful content/parallel-tree precedents, not a
reason to import their full store or OS-update machinery.

The current bundled runtime is a publisher stop condition. First startup runs
`conda-unpack` inside the release tree and creates `.h2ometa-conda-unpacked`;
relocation can also write the absolute runtime prefix into installed files. A
staging directory renamed to a digest-derived final path may therefore contain
the wrong prefix, while post-publication relocation immediately invalidates the
recorded tree.

The official conda-pack documentation closes the tempting shortcuts. In the
default flow the target location needs `conda-unpack` to clean prefixes, and
after `conda-unpack` has executed the environment cannot be relocated again.
With `--dest-prefix`, prefixes are rewritten to the exact absolute destination
at packaging time and no `conda-unpack` script is generated. That can work only
when the immutable destination is already known; it does not make the archive
independent of its final path.

The recommended publisher direction is therefore an opaque, never-reused real
final path. Reserve that path, perform extraction and relocation in place,
verify the resulting bytes, apply final read-only modes, construct the
canonical manifest, and fsync the tree and required parents there. Only then
commit authority with a durable no-replace marker stored outside the release
tree. Before the marker the directory is non-authoritative; after the marker it
is immutable. A proven relocation-free artifact remains an alternative, but
both directions require removal of startup-time `conda-unpack` and execution
through mutable `current/runtime`. Key-store work may proceed in parallel with
this stop condition; generation publication must wait for both authoritative
dependencies.

The 2026-07-18 code-path audit found two additional startup writes and authority
leaks. The PID helper derives `runner.pid` from the installed release root, and
the Python and shell stop/check paths create or remove that file. The systemd
unit and background launcher also still execute through mutable `current`.
Consequently, deleting the `conda-unpack` call alone cannot establish immutable
startup. PID, owner, socket, log and runtime state must move to the shared
mutable namespace, while the unit eventually executes an already verified exact
real release path. `current` can remain only as a post-commit diagnostic view.

The next architecture-track slice is a dormant publication foundation. A
128-bit lowercase hexadecimal publication ID uniquely derives
`release-objects/<publicationId>`; callers never provide a descendant path and
IDs are never reused. An external exact intent binds installation, artifact
version/platform, archive digest/size, the embedded `bootstrap_manifest.json`
semantic fingerprint, provenance fingerprint, and pinned
materialization/extraction/relocation policies. The
external manifest and final receipt remain separate no-replace records. The
receipt binds the normalized intent fingerprint, actual tree-content and
manifest fingerprints, and local root device/inode. None of these records alone
constitutes `prepared`; authoritative replay still requires a complete exact
tree reproof.

The fixed capability namespace is `release-objects` below the anchored runner
root and `shared/activation/release-publications/{.staging,intents,manifests,
markers}` below the already gated activation directory. Dynamic entries require
`openat2(RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS |
RESOLVE_NO_XDEV)`. The upstream Linux interface explicitly states that
`RESOLVE_NO_XDEV` rejects mount-point traversal including bind mounts. Missing
kernel/ABI/flag support and `EXDEV` are hard failures; there is no pathname-check
fallback. Required Ubuntu CI provisions a real bind mount and requires the child
open to fail with exactly `EXDEV`. The Linux `fsync` interface also states that
syncing a file does not necessarily persist its containing directory entry, so
the publisher must sync each unique file and directory plus every external-record
parent in order.

This foundation does not extract archives, execute artifact code, relocate an
environment, create an authority marker, or change protocol v5/bootstrap. A
later extractor must reject duplicate and prefix-colliding members, special
files, link escapes, resource bombs and ungoverned metadata. Relocation must
happen at the exact final path and prove that no descendant process or writable
descriptor survives. A fresh session must never adopt or continue a markerless
partial tree: it is abandoned and a new publication ID is required. Only a
possibly committed marker can be reconciled, through exact external-record and
full-tree proof.

#### Exhaustive archive-inspection update (2026-07-18)

The archive-specific follow-up used more than ten Firecrawl search angles and
scraped over twenty-five upstream, standards, kernel, and security sources. It
covered CPython/tarfile and PEP 706, POSIX pax and GNU tar semantics,
libarchive's secure-extraction flags, Linux pathname/publication syscalls,
conda-pack source and relocation, OCI layer/descriptor rules, CWE resource/path
weaknesses, and OWASP archive-upload guidance. The result strengthens, rather
than relaxes, the earlier stop condition: neither `TarFile.data_filter` nor a
post-hoc pathname check is the installed-tree security boundary.

Python's documentation explicitly requires prior inspection of untrusted
archives, warns that filters do not stop denial-of-service, and notes that an
exception can leave a partially extracted tree. PEP 706 deliberately keeps
filters as policy hooks rather than promising a universal safe extractor.
Libarchive exposes separate flags for `NOABSOLUTEPATHS`, `NODOTDOT`, secure
symlinks and no-overwrite, which is useful corroboration that these are
independent decisions. GNU tar likewise recommends an empty trusted extraction
directory and treats links and writable ancestors as separate risks. H2OMeta
therefore uses Python tar parsing only for a future bounded inspector and
regular payload reader; it will never call `extract`, `extractall`,
`shutil.unpack_archive`, or shell `tar` in the authority publisher.

A read-only sample of the repository's old 0.1.1 control-plane bundle contained
13,468 members, including 1,175 symlinks and three hardlinks. Most symlink
targets containing `..` still resolved inside the tree. This sample is not
current-artifact acceptance evidence, but it disproves the tempting rule
"reject every link". The accepted model is an explicit internal link graph:
relative symlinks may contain `.`/`..` only when complete graph resolution stays
inside the root, terminates, and has bounded depth. Raw archive hardlinks may
target any canonical regular member, never another link or a directory. Before
installed-tree validation, each inode-alias group is rewritten so its
lexicographically first path is the sole canonical file and every later path is
a hardlink to it; one real tree therefore has only one portable identity.

The first dormant archive manifest is intentionally an inspection-record
contract, not a tar reader. It binds exact compressed archive SHA-256 and byte
length, the inspector-observed decompressed tar-stream byte length, `tar+gzip`,
extraction policy v1, derived member and byte totals, and an ordered normalized
member list. Each member has only path, type, source mode, size, regular-file
content SHA-256, and link target. The contract closes printable ASCII
component/path rules, explicit directory parents, duplicate/prefix collisions,
file/directory/symlink/hardlink metadata, internal link graph, member count,
per-file bytes, aggregate payload/logical-tree bytes, aggregate canonical
member-record bytes, full canonical manifest bytes, compressed and raw-stream
absolute limits, and the raw-stream compression ratio. Tar headers, padding,
PAX records, and GNU long-name records therefore cannot bypass the ratio with a
tiny regular payload. It accepts only source file modes `0644|0755`, directory
`0755`, and symlink `0777`; special/sparse/unknown types are outside policy.

The record embeds the exact normalized semantic object parsed from the fixed
regular member `bootstrap_manifest.json`, its raw-content SHA-256, and its
domain-separated semantic fingerprint. A shared core contract caps the raw JSON
at 1 MiB, rejects duplicate keys, non-finite numbers and invalid UTF-8, and
closes service, version, platform, bundled-runtime and runner-protocol fields.
The startup preflight and future inspector use the same existing
`h2ometa.remote-runner.startup.bootstrap-manifest.v1` identity. Publication
intent v2 retains that bootstrap identity and adds a separate
`archiveInspectionManifestFingerprint`; the archive binder compares both
identities plus version, platform, archive digest/size, and extraction policy.
The repository release declaration, embedded bootstrap manifest, archive
inspection record, and installed-tree manifest are four distinct documents. No
field is reused for more than one.

Raw tar UID/GID, uname/gname, mtime, PAX keys, GNU sparse metadata, device
numbers, xattrs, ACLs, capabilities, and exact `./` spelling are deliberately
not fields callers may assert in that normalized contract. The future real
inspector must reject any non-policy raw metadata before constructing the
record. It must also snapshot a held regular archive fd, prove fstat identity
before and after, make two bounded passes, reject normalization collisions, and
hash every regular payload. A self-consistent manifest still proves none of
those observations.

Extraction policy v1 now closes that raw envelope to POSIX.1-1988 USTAR with
the exact USTAR magic/version. Tar UID, GID, and mtime are zero; uname/gname are
empty; devmajor/devminor are zero. The only semantic types are regular file,
directory, symlink, and hardlink. GNU `L`/`K` long-name/long-link records, local
or global PAX headers, GNU sparse records, devices, FIFOs, and every other
special or unknown type are rejected. A path or numeric field that USTAR cannot
represent makes the builder fail; GNU/PAX extension fallback is forbidden. Raw
name normalization may remove exactly one trailing `/` from a directory member,
ignore one resulting root `.`/`./` directory header, and remove exactly one
leading `./` from a non-root member name or hardlink target. It must not use
`strip("./")`, remove repeated prefixes or slashes, or rewrite symlink target
text; any remaining absolute, dot-component, duplicate, or normalization
collision is a hard failure.

Mode, UID, GID, size, and mtime use fixed-width, zero-padded octal digits
followed by NUL; inactive devmajor/devminor fields are all NUL. The checksum is
exactly six octal digits, NUL, and space. A regular member uses the exact `0`
typeflag. Numerically equivalent space padding and the legacy NUL regular
typeflag are rejected rather than treated as compatibility encodings.

The gzip envelope is equally closed: exactly one member, zero MTIME, and
`FLG == 0`. FEXTRA, FNAME, FCOMMENT, FHCRC, reserved FLG bits, a concatenated
second member, and every byte after the sole member are rejected. The inspector
must consume compressed EOF and verify CRC/ISIZE instead of treating a gzip
parser stop position as archive EOF.

The successful held-FD result is a single-owner, non-copyable, non-pickleable
process capability. One lock serializes reads, proofs, and close. On the main
thread, SIGINT is deferred only across the short `F_DUPFD_CLOEXEC`-to-owner
handoff; Python signal handlers do not execute on non-main threads. The duplicate
is immediately owned by CPython 3.12+ native `_io.FileIO(closefd=True)`.
Capability close, outer failure cleanup, and the `_io.FileIO` deallocator share
that one owner. CPython invalidates the owner's internal fd in C before releasing
the GIL and entering `close(2)`, so a close error or `KeyboardInterrupt` cannot
leave a stale fd number available for a second close. A Python close-state and
per-thread `pthread_sigmask` are not treated as atomic ownership. The capability
never returns its owned FD and instead offers positional reads with identity proofs before and
after each call. Once a descriptor is adopted, every failure is re-proved before
classification: storage drift or unavailability outranks archive rejection,
while cleanup can never downgrade a body `outcome_unknown`. Fresh fixed public
errors have no cause or context from which errno, paths, or raw policy details
could be recovered.

The archive graph now also yields one runtime-only pre-relocation
materialization projection. It is derived only after complete archive-manifest
revalidation and is ordered by canonical path. Exactly one canonical file
consumes each raw USTAR regular payload through `payloadSourcePath`; directories,
symlinks, and hardlinks have no payload route. If a hardlink alias sorts before
the raw regular member, the alias becomes the canonical file and routes payload
from that later raw path, while the raw path becomes a hardlink back to the
alias. Removing `payloadSourcePath` yields the existing portable tree-content
identity, but the route is deliberately outside that identity.

This projection is not serialized as a plan and is not a filesystem
observation, receipt, marker, or authority. Conda relocation at the exact final
path may legitimately change regular-file bytes and sizes, so raw archive hashes
cannot stand in for the final tree. Future portable relocation evidence must
bind the archive inspection manifest, deterministic source projection, exact
pre/post relocation observations, and the sealed fresh-walk final tree. Until
that evidence and a receipt version that consumes it exist, no authority marker
or `prepared` claim may be emitted and no production path may consume the slice.

The declared 0.1.5 control-plane archive (SHA-256
`d9624da99cff5334a92b53a48a4176a421d1e9b27da23a339939aaa6eaf9b961`,
105,989,502 bytes) is not yet acceptance evidence for this policy. Conda-pack
0.9.1 emitted `runtime/bin/conda_unpack_progress.py` with mode `0600`; its
bootstrap JSON also has a legacy `build` object and lacks the required
`runnerProtocol` and `runnerProtocolFingerprint`. Its three raw hardlinks are
safe under the two-phase canonicalization above. The repository artifact builder
now deterministically normalizes non-executable regular files to `0644`, executable
files and directories to `0755`, emits the exact current bootstrap contract, and
builds under `umask 077`. Its archive pipeline uses USTAR, sorted names, zero
owner/group/mtime, and one `gzip -n` member; shell `pipefail` makes a USTAR path
limit or tar failure fail the build rather than silently selecting an extension.
The published 0.1.5 archive and every artifact produced before this envelope
policy must be rebuilt by that builder before becoming an acceptance candidate;
none is grandfathered. The older 0.1.1 sample is useful only for link topology;
it has 242 non-policy modes, GNU long-name records, and a legacy
`.h2ometa-conda-unpacked` member, so it is explicitly rejected as an acceptance
fixture.

The later materializer reserves the opaque final directory first, extracts
there through held directory fds, and performs conda relocation at that exact
path before sealing. It creates regular files exclusively, creates hardlinks
only from verified primary inodes, and creates symlinks last without traversing
them. It then applies read-only modes, fsyncs unique files and directories,
closes writable descriptors, walks the real tree afresh, and only then commits
external evidence and a marker. Markerless trees are abandoned; a possible
marker commit followed by any uncertain durability or reproof result is
`outcome_unknown`.

The first fd-relative implementation slice now shares the release-tree entry
component validator with that manifest contract and adds a dormant dynamic
directory `openat2` contract boundary. It uses the same exact directory flags and
`RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS |
RESOLVE_NO_XDEV` policy as the fixed publication layout. Only `EAGAIN` is
retried, for at most three identical calls; unsupported ABI, invalid `open_how`,
cross-mount, symlink, and interrupted calls fail immediately without a path or
`openat` fallback.

The contract suite proves the validation, call shape, retry budget, post-open
checks, and no-fallback behavior against an injected syscall boundary. The
required Ubuntu activation-storage job now separately proves a real dynamic
child identity and non-inheritance, fail-closed final-symlink refusal, and
bind-mount `EXDEV`. Current supported kernels may report either `ELOOP` from
`RESOLVE_NO_SYMLINKS` or `ENOTDIR` from the combined `O_DIRECTORY | O_NOFOLLOW`
check; neither result opens the target. This is kernel evidence on the required
CI platform, not proof for an untested architecture, kernel, mount, or
production runner host.

Required-platform acceptance is recorded by GitHub Actions
[run 29624601618](https://github.com/jiangzheyi1234-star/bioinfo-platform/actions/runs/29624601618),
job `python / activation-storage-linux`, at source
`21034548deac586e5935cf8a46fbc5c7fe295ed4`: 574 passed and 6 skipped on
Ubuntu 24.04 / Linux 6.17 x86_64. The run also exposed and then drove separate
partial key-layout cleanup and archive ancestor-replacement fixture fixes; the
recorded successful job includes both corrections.

That Python boundary intentionally says `raw_fd` and is not a production
capability. `O_CLOEXEC` prevents inheritance across `execve`, but does not close
an abandoned descriptor in the current process. CPython `_io.FileIO` cannot
adopt a directory descriptor, so the archive-file SIGINT handoff proof does not
generalize to directories. Before a materializer may retain a directory fd, it
must either use a native owner whose single C-level operation opens and adopts
the descriptor with deallocation cleanup, or keep all directory-fd work inside
one synchronous, SIGINT-deferred stack operation that closes before returning.
The dormant raw-fd contract is not wired into startup, publication, or generation
authorization.

The first prerequisite now has a quarantined, dormant implementation, but it is
not production wiring. Production and proof use distinct distributions,
modules, `PyInit_*` entry points, and capsule identities. The production surface
is limited to `_open_child`, `_require_live`, and `_close`; it exposes no root
seed, raw fd, path open, callback, replay, or fallback.

Required-platform evidence is GitHub Actions
[run 29630042088](https://github.com/jiangzheyi1234-star/bioinfo-platform/actions/runs/29630042088),
[job `python / native-activation-fd-owner-linux`](https://github.com/jiangzheyi1234-star/bioinfo-platform/actions/runs/29630042088/job/88041786548),
at source `8722fec795baadf72b9d024d442d041213f609c4`. That job concluded
`success` on the Ubuntu 24.04 x86-64 runner image `20260714.240.1`. CPython
3.12.13 built
`h2ometa_activation_release_dir_owner-0.1.0-cp312-abi3-linux_x86_64.whl`
and
`h2ometa_activation_release_dir_owner_proof-0.1.0-cp312-abi3-linux_x86_64.whl`;
both imported under CPython 3.12.13 and 3.13.14. The controlled validator
checked wheel identity, one extension, ELF64 x86-64 `DYN`, RELRO/NOW, exported
symbols, the Stable ABI allowlist, prohibited path-fallback symbols, extra
native payloads, and symlinks. `abi3audit 0.0.26 --strict` also completed
successfully. Real bind-mount, foreign-UID refusal, `openat2` fail-closed, and
symlink-refusal checks provide real syscall evidence. Injected boundaries cover
retry and error shapes. A proof hook reports an injected post-close `EINTR`
only after the real close has completed; this is not evidence that the kernel
`close()` returned `EINTR`. The combined contract, wheel-validator, and
proof-binary behavior suite ended with 51 passed, including descriptor
reuse/double-close, destructor, SIGINT, and `sys.monitoring.INSTRUCTION`
return-boundary coverage.

Behavioral evidence belongs only to the separately identified proof binary.
The production binary intentionally has no root seed, so its evidence is
limited to build, ABI, import, and surface checks. Both wheels were built and
discarded under `$RUNNER_TEMP`; neither was uploaded, bundled, or connected to
startup, publication, or generation. This records the required job's successful
conclusion. The parent workflow run concluded `failure`, so this is neither
whole-CI nor branch-acceptance evidence, and it does not generalize to another
architecture, libc, kernel, mount, or production host.
Production adoption still requires root/session capsule ownership, exact
runtime and glibc qualification, artifact hash/SBOM/provenance, versioned
archive import, and startup preflight.

The next dormant implementation boundary is specified by the
[capsule-only directory leaf-primitives research](2026-07-18-capsule-only-directory-leaf-primitives.md).
It adds only create-only directory ownership and explicit directory sync; it
does not begin file/link replay or production wiring.

Contrarian limits remain. Fixed quotas are availability policy, not a proof
that memory, CPU, disk allocation, or decompressor implementation has no bugs.
ASCII-only names and normalized modes trade artifact generality for a closed
execution surface. Link-graph acceptance does not make links safe to traverse
during extraction. The installed-tree publisher still cannot enter production
until startup relocation, release-root PID/marker writes, and mutable `current`
execution are removed.

Research rerun inputs:

```text
workflow: firecrawl-deep-research
topic: secure tar+gzip inspection, fd-relative materialization, conda-pack relocation, and durable installed-tree publication
depth: exhaustive (no time limit)
output: markdown decision update
```

### 6. Systemd credentials are an optional stronger backend

`LoadCredentialEncrypted=` can decrypt and authenticate credentials at unit
activation into a read-only per-unit credential directory and can bind an
encrypted blob to systemd's machine credential secret, TPM2, or both. This is
not the SSH host key. It is preferable to a plaintext
application-owned file where systemd version, TPM availability, recovery, and
migration policy are proven.

It is not a silent fallback or an HSM. The service receives plaintext while
running, same-service UID/root compromise remains in scope, unit limits apply,
and host/TPM binding makes disaster recovery and migration operationally
significant.

## Threat model and contrarian limits

- Modes `0700`/`0600`, link-count checks, and nofollow traversal do not defend
  against root, relevant capabilities, or a malicious process running as the
  same UID.
- `flock` is advisory cooperation, not authorization, distributed fencing, or
  a defense against a noncooperating same-UID writer.
- ext4/XFS allowlisting does not prove physical durability. Mount options,
  barriers, volatile device caches, firmware, and real power loss remain
  outside CI's syscall proof.
- Required Ubuntu tests prove the Linux state machine and syscalls. A future
  controlled block-device/power-cut test and production-mount acceptance are
  stronger evidence.
- Installation intent/final enrollment is not SSH host enrollment. Host-key
  rotation, cross-host restore, and secret import/export require explicit
  audited re-enrollment rather than automatic adoption.
- Deletion by root or the service UID of the final phase and the entire
  activation namespace is indistinguishable locally from a virgin root even
  if the empty stable gate remains. It is outside this local threat model.
  A controller-side monotonic witness must stop when a previously enrolled
  installation reports local virgin state; only an explicit audited reset may
  authorize destructive recovery.

## Resulting implementation sequence

1. Hold the stable shared lifecycle gate, persist the pre-activation intent,
   recover the exact fixed skeleton only for that identity, and atomically
   promote intent to final only after the complete child-capability and empty
   authority proof. Keep protocol v5 and production mutation paths unchanged.
2. Define canonical installed release-tree identities without treating a
   self-consistent manifest as storage or publication proof.
3. In parallel: (a) remove the startup-time relocation/write boundary and
   publish/reprove installed trees using an opaque never-reused final path plus
   an external no-replace commit marker (or a proven relocation-free artifact);
   and (b) persist/reconcile versioned config-integrity key material through the
   dynamic scoped store, deterministic pending name, and fresh-session recovery.
4. Publish verified immutable generation directories only after tree and key
   dependencies are authoritative.
5. Add transition and invocation journals.
6. Introduce protocol v6 startup verification.
7. Move bootstrap, rotation, rollback, prune, and uninstall behind the same
   global lifecycle gate; remove mutable legacy paths rather than adding silent
   compatibility fallbacks.

## Open questions

- Which production mount options and storage hardware form the first supported
  remote-runner acceptance profile?
- Is systemd encrypted credential custody mandatory for managed deployments or
  an optional backend beside private-file storage?
- What controller-side schema binds installation fingerprint, SSH host key,
  endpoint identity, and audited re-enrollment?
- What retention policy preserves rollback reachability without claiming
  secure deletion on SSD/COW storage?

## Primary sources

- [Linux open(2)](https://man7.org/linux/man-pages/man2/open.2.html)
- [Linux fsync(2)](https://man7.org/linux/man-pages/man2/fsync.2.html)
- [Linux rename/renameat2(2)](https://man7.org/linux/man-pages/man2/rename.2.html)
- [Linux write(2)](https://man7.org/linux/man-pages/man2/write.2.html)
- [Linux close(2)](https://man7.org/linux/man-pages/man2/close.2.html)
- [CPython 3.12 `_io.FileIO` implementation](https://github.com/python/cpython/blob/v3.12.10/Modules/_io/fileio.c)
- [Python signal handling](https://docs.python.org/3/library/signal.html)
- [Python 3.12 `sys.monitoring`](https://docs.python.org/3.12/library/sys.monitoring.html)
- [CPython 3.12.13 bytecode implementation](https://github.com/python/cpython/blob/v3.12.13/Python/bytecodes.c)
- [Linux stat(2)](https://man7.org/linux/man-pages/man2/stat.2.html)
- [Linux openat2(2)](https://man7.org/linux/man-pages/man2/openat2.2.html)
- [Linux getrandom(2)](https://man7.org/linux/man-pages/man2/getrandom.2.html)
- [Linux flock(2)](https://man7.org/linux/man-pages/man2/flock.2.html)
- [Linux capabilities(7)](https://man7.org/linux/man-pages/man7/capabilities.7.html)
- [Python secrets](https://docs.python.org/3/library/secrets.html)
- [conda-pack deployment flow and relocation caveat](https://conda.github.io/conda-pack/)
- [conda-pack CLI `--dest-prefix`](https://conda.github.io/conda-pack/cli.html)
- [PEP 524: blocking `os.urandom`](https://peps.python.org/pep-0524/)
- [Python bytes, bytearray, and memoryview](https://docs.python.org/3/library/stdtypes.html)
- [CPython memory management](https://docs.python.org/3/c-api/memory.html)
- [systemd credentials design](https://systemd.io/CREDENTIALS/)
- [systemd.exec credential directives](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)
- [RFC 5869: HKDF](https://www.rfc-editor.org/rfc/rfc5869.html)
- [NIST SP 800-108r1](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-108r1.pdf)
- [Python tarfile extraction filters](https://docs.python.org/3/library/tarfile.html)
- [conda-pack 0.9.1 source: generated text-file mode behavior](https://github.com/conda/conda-pack/blob/0.9.1/conda_pack/core.py)
- [PEP 706: tarfile extraction filters](https://peps.python.org/pep-0706/)
- [POSIX pax](https://pubs.opengroup.org/onlinepubs/9699919799/utilities/pax.html)
- [GNU tar manual and archive security guidance](https://www.gnu.org/software/tar/manual/tar.html)
- [libarchive extraction options](https://github.com/libarchive/libarchive/blob/master/libarchive/archive_read_extract.3)
- [Linux kernel pathname lookup](https://docs.kernel.org/filesystems/path-lookup.html)
- [Linux link/linkat(2)](https://man7.org/linux/man-pages/man2/linkat.2.html)
- [Linux unlink/unlinkat(2)](https://man7.org/linux/man-pages/man2/unlink.2.html)
- [Linux mkdir/mkdirat(2)](https://man7.org/linux/man-pages/man2/mkdir.2.html)
- [Linux statx(2)](https://man7.org/linux/man-pages/man2/statx.2.html)
- [CWE-22: path traversal](https://cwe.mitre.org/data/definitions/22.html)
- [CWE-409: improper handling of highly compressed data](https://cwe.mitre.org/data/definitions/409.html)
- [OWASP file upload cheat sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
- [OCI image layer filesystem changeset](https://github.com/opencontainers/image-spec/blob/main/layer.md)
- [TUF specification](https://theupdateframework.github.io/specification/latest/)
- [in-toto Statement v1](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md)
- [OCI descriptor specification](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)
- [OCI image index specification](https://github.com/opencontainers/image-spec/blob/main/image-index.md)
- [SLSA v1.2 build provenance](https://slsa.dev/spec/v1.2/build-provenance)
- [SLSA v1.2 artifact verification](https://slsa.dev/spec/v1.2/verifying-artifacts)
- [Nix content addressing](https://nix.dev/manual/nix/2.33/store/file-system-object/content-address)
- [OSTree repository model](https://ostreedev.github.io/ostree/repo/)
- [OSTree atomic upgrades](https://ostreedev.github.io/ostree/atomic-upgrades/)
- [Git tree object model](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects)
- [RFC 8785: JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785.html)
- [ext4 administration guide](https://docs.kernel.org/admin-guide/ext4.html)
- [XFS delayed logging design](https://docs.kernel.org/filesystems/xfs/xfs-delayed-logging-design.html)
- [OverlayFS documentation](https://docs.kernel.org/filesystems/overlayfs.html)
