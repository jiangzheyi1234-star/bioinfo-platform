# Runner activation storage trust-root research

Date: 2026-07-17
Status: decision input for the dormant Agent-first activation control plane

## Executive summary

The next safe implementation step is not generation publication or secret-key
storage. The runner first needs an immutable two-name enrollment phase
promotion that binds one canonical `runnerRoot` to one installation record, plus a
session that continuously reproves every retained child file descriptor
against its canonical pathname.

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

### 4. Key storage is the next separate dependency

After enrollment, versioned config-integrity keys can use the same no-replace
protocol under private `0700` directories. Each final file contains exactly 32
raw bytes, has mode `0600`, current UID, link count one, and is named only from
a validated key ID. Exact retries compare fixed-length bytes with
`hmac.compare_digest`; observations expose fingerprints and dispositions, not
material, paths, raw IDs, or tags.

Random material should come from `secrets.token_bytes(32)`/the OS CSPRNG. On
Linux, Python's `os.urandom` uses blocking `getrandom` semantics so it does not
return weak early-boot entropy. `GRND_RANDOM` is unnecessary.

Python cannot promise complete memory erasure: immutable `bytes`, allocator
arenas, hash/HMAC temporaries, stack, and register copies may remain. Mutable
buffers may be overwritten as best effort, but a verified erasure requirement
needs a native isolated component, TPM/HSM, KMS, or another custody boundary.

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
2. Define and publish canonical installed release-tree identities.
3. Persist/reconcile immutable versioned config-integrity key material.
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
- Which path-byte and Unicode policy should the installed-tree manifest adopt?
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
- [Git tree object model](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects)
- [RFC 8785: JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785.html)
- [ext4 administration guide](https://docs.kernel.org/admin-guide/ext4.html)
- [XFS delayed logging design](https://docs.kernel.org/filesystems/xfs/xfs-delayed-logging-design.html)
- [OverlayFS documentation](https://docs.kernel.org/filesystems/overlayfs.html)
