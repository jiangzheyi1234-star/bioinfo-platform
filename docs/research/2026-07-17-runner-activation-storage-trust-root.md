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
