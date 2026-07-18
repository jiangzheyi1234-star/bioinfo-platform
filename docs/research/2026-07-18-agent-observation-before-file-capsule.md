# Deep Research: Agent observation before the regular-file capsule

Date: 2026-07-18
Status: decision input for the next Agent-first slice; not activation enablement

## Executive summary

H2OMeta should not implement the dormant regular-file capsule as its next
product slice. That primitive is independently provable, but it still has no
runtime consumer and its eventual interface is constrained by decisions that
are not closed: verified decompressed-payload replay, journal/orphan semantics,
ACL/xattr policy, relocation order, trusted-root fresh walk, receipt/marker
publication, production root issuance, and native artifact provenance.

The next slice should instead add a small, frontend-only
`agent-session-observation.v1` projection to the Agent Workbench. It is derived
from the existing atomic `agent-session-snapshot.v1`; it creates no database,
endpoint, mutation, vendor dependency, or telemetry exporter. It answers four
questions that the current Agent-first experience does not answer directly:

1. What durable state is the session in?
2. Who or what must act next?
3. What client-clock estimate is available for the current state's age, with
   explicit skew limitations?
4. How much of the one currently measurable hard budget, replans, has been
   consumed?

The projection must not invent model-turn, tool-call, retry, token, cost, wall
clock, or stalled/SLA facts. Those require new authoritative provider-neutral
events. It must not export prompts, event payloads, tool inputs/outputs, paths,
credentials, or reasoning. This makes the slice immediately useful while
preserving the remote runner as the only durable source of Agent facts.

The activation track is not abandoned. Its next implementation remains gated
by a separate file-capability contract decision. A future regular-file capsule
may use exact bounded `bytes` chunks and explicit monotonic offsets, or a larger
native archive-transfer operation; this research deliberately does not freeze
that choice prematurely.

## Research method

The repository was inspected at
`2a26d8375c36df327d8a1c4294dec453406720d6`. Three read-only agents reviewed,
respectively, the local archive/materialization boundary, a complete Linux and
CPython file-write state machine, and a contrarian priority ranking. A fourth
read-only agent inspected the current Agent snapshot, Workbench, API, and UI
boundary.

Firecrawl was run through the repository wrapper at the exhaustive/no-time-limit
tier. The combined decision collection contains 23 structured searches, 124
results, and 119 unique URLs, plus direct primary-source scrapes. Sources were
selected from CPython, Linux man-pages/kernel documentation, POSIX, conda-pack,
OpenTelemetry, OpenAI Agents SDK, Temporal, Microsoft architecture guidance,
Langfuse, GitHub artifact attestations, OCI, SLSA, and filesystem research.
Search result quality was checked before synthesis; claims below prefer primary
documentation and clearly identify inferences.

Temporary `.firecrawl/file-capability-research/` output is ignored local
evidence. It is not a source, build, release, or runtime artifact.

## Current Agent control-plane boundary

The accepted [Agent-first ADR](../adr/2026-07-15-agent-first-control-plane.md)
already makes the important product decision: a goal-driven workbench is the
primary authoring surface, while the deterministic graph remains a compiled,
validated, lineage-bearing expert projection. The graph is not the planner,
conversation, retry loop, or source of truth.

The current implementation has a strong durable base:

- `apps/remote_runner/agent_session_schema.py` stores immutable plans,
  approvals, and append-only `agent_events`; update/delete triggers protect the
  event and approval ledgers.
- `apps/remote_runner/agent_snapshot_storage.py` reads the session, complete
  ordered events, plans, and approvals in one transaction. It recomputes the
  full event hash chain, including the private command hash, before returning
  `agent-session-snapshot.v1`.
- `core/contracts/agent_snapshot.py` verifies sequence continuity, payload
  hashes, previous-hash links, session/head status and generation, plan
  lineage, and approval binding.
- The Workbench already shows status, plans, approvals, and the event timeline,
  but it does not summarize the current attention owner, state residence time,
  or observable budget consumption.

The browser cannot recompute the complete event hash because public
`AgentEvent` deliberately omits `commandHash`. It can verify public sequence and
previous-hash linkage, while the atomic runner read proves the complete chain.
The UI must say exactly that; it must not relabel a partial browser check as an
end-to-end cryptographic verification.

## Why a read-only observation is the next useful slice

The external systems converge on a useful distinction:

- OpenAI Agents SDK models one run as a trace composed of nested spans for
  runner work, model turns, agents, generations, tools, guardrails, and
  handoffs. It also warns that generation and function spans can contain
  sensitive inputs and outputs, and lets callers disable that capture.
- Temporal's event history is the durable recovery source, while logs and
  observability are projections; its SDK guidance avoids replaying logs by
  default because a projection must not become a second side-effect source.
- Microsoft's CQRS guidance treats the read model as a query projection and
  notes that event-sourced views can be rebuilt by replaying authoritative
  events.
- OpenTelemetry's GenAI attributes and events are still marked Development.
  Input/output messages, prompt variables, system instructions, and tool
  definitions are opt-in content fields. Token counts are useful attributes,
  but they are facts a provider operation must actually report.
- Langfuse recommends masking before trace data leaves the application and
  warns that filtering spans can break parent-child trace structure.

The inference for H2OMeta is narrow: derive a versioned local view from the
already validated snapshot now, but do not make a changing external semantic
convention part of the durable Agent contract. Provider tracing can later map
to an exporter from new provider-call facts. The first observation should
remain lossless with respect to its small input facts and should export nothing.

## Proposed `agent-session-observation.v1`

The projection is a pure TypeScript value, never a remote contract:

```text
source
  sessionId, stateVersion, planGeneration
  clientObservedAt
  headSequence, headEventHash, headEventAt

lifecycle
  status, stateEnteredAt
  stateAgeSeconds | null
  timingStatus = client_estimate | invalid_timestamp | clock_regression
  attention = plan_not_started
            | planning_recovery_available
            | human_approval_required
            | plan_failed
            | typed_replan_required
            | run_authorization_pending
            | terminal

counters
  events, plans, approvals
  replansUsed, replansRemaining
  planFailures, changeRequests

integrity
  runnerFullChain = required_by_snapshot_endpoint
  browserSequence = verified
  browserPrevHashLinks = verified
  browserEventHash = not_verifiable_command_hash_redacted

redactionPolicy
  eventPayloadsDisplayed = false
  commandHashesExposed = false
  requestIdentitiesDisplayed = false
  actorsDisplayed = false
  pathsOrUrisDisplayed = false
  rawModelOutputDisplayed = false
  credentialsDisplayed = false
```

The pure derivation receives an explicit observation epoch so tests do not
depend on the wall clock. It validates the snapshot's existing order rather
than sorting it, requires exact sequence `1..N`, checks genesis and every
previous-event link, and checks that the head status/generation and maximum
state version match the session projection.

`stateEnteredAt` is found by scanning backward for the first event whose
`toStatus` equals the current session status and whose `fromStatus` differs.
The genesis `null -> created` transition is valid; no match is an integrity
error, not permission to fall back to a same-status event. Consequently an
event such as `agent.approval_granted` cannot reset time spent awaiting
approval. An invalid timestamp or a client clock earlier than the state
timestamp yields `stateAgeSeconds = null` and an explicit timing status;
neither case may be called stalled or timed out.

A nonnegative result is only `client_estimate`, never `ok`: the browser can
detect a clock that is behind the event, but it cannot detect a client clock
that is hours ahead. The panel must label the duration as a client estimate and
must not treat it as trusted server elapsed time.

The one currently measurable budget is replans. The projection derives
`replansUsed = max(0, planGeneration - 1)` and requires it to equal the exact
count of `agent.replan_requested` events. It must also be no greater than
`maxReplans`; an over-budget snapshot is corrupt and cannot be normalized by
clamping remaining to zero. Model turns, tool calls, retries, tokens, costs,
and authoritative wall-clock consumption are absent, not zero. They must not
appear as consumed-budget metrics until their own append-only facts exist.

Every structural derivation failure uses a stable error code only. It must not
include snapshot JSON, payloads, actors, request identities, paths, or other
sentinels in an exception message.

## Why the regular-file capsule is deferred

The read-only reviewers agreed on the materialization blockers even though one
reviewer ranked the dormant primitive itself as the next independently
provable implementation.

The archive inspector retains a stable regular-file capability, but its private
positional read operates on compressed bytes. The two-pass gzip/USTAR inspector
hashes non-bootstrap regular payloads and discards them. `payloadSourcePath`
routes a raw USTAR member to a canonical installed file; it is not an offset,
bounded stream, or replay plan. Therefore the repository has no verified
decompressed payload consumer for a file-writing capsule.

A correct future file owner also needs a distinct identity and state machine:
create-only `openat2`, immediate adoption, initial private mode, an exact
bounded partial-write loop with explicit monotonic offset, final-mode fixup,
file `fsync`, poisoning after uncertain writes, and single-close semantics.
Parent-directory `fsync` remains the existing directory leaf or an orchestrator
step, not a file-owner responsibility. The Linux and CPython audit found that
the file owner can be proven with synthetic bytes while remaining disconnected.

Before that isolated dormant proof resumes, four items must be frozen:

1. exact-bytes chunk ingress versus a native archive reader;
2. chunk and expected-file size limits;
3. the proof-only final mode profile plus exact syscall/state/error/identity
   contract: create-only strict
   `openat2`; immediate adoption; bounded resolver-`EAGAIN` retry only;
   issued-`EINTR` name burn; positive `pwrite` short writes advance the offset
   and continue inside the same C call, while zero or error including `EINTR`
   poisons without Python replay; no retry of `fchmod`, `fsync`, or `close`;
   exact regular/CLOEXEC/dev/inode/UID/
   same-device/link-count/size proofs; and pre/post reproof for every leaf.
4. sibling extension/ABI shape and the standard-GIL CPython 3.12/3.13/3.14
   Ubuntu proof matrix.

Create/adopt and each single-chunk partial-write loop must each finish inside
one C call. Initial `fchmod(0600)` closes umask/default-mode ambiguity but does
not prove ACL/xattr absence. File `fsync` and same-parent directory `fsync`
remain separate leaves; file sync alone does not make the namespace entry
durable. A retained descriptor does not prove final pathname binding.

Production or authority wiring has a separate, larger gate: verified real
payload replay and provenance; opaque staging journal/orphan quota and
fresh-session reconciliation; relocation ordering and pre/post evidence; full
ACL/xattr/capability policy; trusted-root fresh reopen/walk and production
filesystem/mount/storage acceptance; controlled native artifact provenance and
root issuance; and receipt/marker-last publication. Those requirements do not
prevent a disconnected proof, but they prevent that proof from becoming a
materializer or execution authority.

Implementing the C API before those decisions would optimize an unreachable
boundary and could force a source-compatible-looking but semantically wrong
API. It remains a valid later proof slice, not the next product slice.

## Relocation-free artifact gate

The official conda-pack CLI documents that `--dest-prefix` rewrites prefixes to
an exact path during packaging and omits `conda-unpack`. This removes runtime
relocation only when the immutable destination is known at build time. H2OMeta
currently distributes one artifact to installations whose opaque final paths
are chosen later, so adopting `--dest-prefix` would imply per-destination
packaging or a different fixed-path release model. It also would not move PID,
socket, log, and other startup writes out of the release tree or remove mutable
`current` from execution authority.

Consequently, `dest-prefix` is a worthwhile activation feasibility experiment,
not an immediate architectural escape hatch. It must prove the complete real
artifact, multi-host distribution model, deterministic bytes, supply-chain
identity, and zero startup writes before it may cancel the materializer track.

## Contrarian views

### “The regular-file capsule is the natural next mechanical step”

This is true if “next” means the next isolated native proof. The existing
directory owner provides a strong template, and a proof-only seed plus synthetic
bytes can validate ownership without a runtime consumer. The objection is
priority, not feasibility: it does not advance the Agent-first product surface,
and its byte-ingress API may be superseded by the journal/orchestrator decision.

### “Observability belongs in an OpenTelemetry backend”

External tracing is useful after provider calls exist. Adding an exporter now
would create configuration, privacy, delivery, and semantic-version questions
without any authoritative model/tool usage events. A local pure projection is
rebuildable, has no delivery failure mode, and preserves exporter choice.

### “Client-derived age is a timeout detector”

It is not. Client clock skew, refresh cadence, human approval wait, and the
undefined treatment of paused time make automatic stall/SLA claims unsafe. The
first UI may display a clearly labeled client estimate only. A negative delta
is detectable, while a fast client clock is not. Server-time SLAs require a
separate contract.

### “All configured budgets can be shown as consumed”

Limits are not usage. The current ledger can count replans; it has no
provider-call, tool-call, retry, token, or cost events. Showing zero would be a
false claim and could later permit work beyond the intended limit.

## Stop conditions

Stop and create a new contract if the slice requires any of the following:

- token, cost, model-turn, tool-call, retry, or authoritative wall-time usage;
- automatic stalled/SLA/timeout classification;
- command hashes, event payloads, prompts, paths, model output, tool arguments,
  tool results, credentials, or reasoning;
- cross-session aggregation, retention, export, sampling, or alert delivery;
- a new remote schema, endpoint, governance action, or mutation;
- resume, retry, cancel, approve, compile, or run submission from the
  observation surface.

For activation, stop file work if it needs a raw descriptor, Python callback,
iterator, best-effort cleanup, markerless-tree adoption, reused publication ID,
unproven metadata normalization, or a wheel without controlled provenance.

## Open questions

- Which provider-neutral events will eventually account for model turns, tool
  calls, retries, provider usage, and cost without persisting sensitive content?
- Does hard wall-clock budget include time awaiting human approval, client
  disconnection, and deliberate pause?
- Should future cross-session operations use a runner-owned materialized view or
  bounded on-demand projections over the event ledger?
- Which internal versioned mapping should export to the evolving OpenTelemetry
  GenAI conventions without making those names part of H2OMeta's durable API?
- Can a real runner artifact prove prefix-free bytes, or does multi-host
  distribution require in-place final-path relocation?
- Does the eventual materializer need exact Python `bytes` chunks or one native
  archive-to-file orchestration operation to reduce cancellation boundaries?

## Sources

- [H2OMeta Agent-first control-plane ADR](../adr/2026-07-15-agent-first-control-plane.md)
- [H2OMeta capsule-only directory research](2026-07-18-capsule-only-directory-leaf-primitives.md)
- [OpenAI Agents SDK tracing](https://openai.github.io/openai-agents-python/tracing/)
- [OpenAI Agents SDK human-in-the-loop](https://openai.github.io/openai-agents-python/human_in_the_loop/)
- [OpenTelemetry GenAI semantic-conventions repository](https://github.com/open-telemetry/semantic-conventions-genai)
- [OpenTelemetry GenAI attribute registry](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/registry/attributes/gen-ai.md)
- [OpenTelemetry GenAI events](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-events.md)
- [Temporal event history](https://docs.temporal.io/encyclopedia/event-history)
- [Temporal TypeScript observability](https://docs.temporal.io/develop/typescript/platform/observability)
- [Microsoft CQRS pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs)
- [Langfuse masking](https://langfuse.com/docs/observability/features/masking)
- [Langfuse observability data model](https://langfuse.com/docs/observability/data-model)
- [conda-pack CLI `--dest-prefix`](https://conda.github.io/conda-pack/cli.html)
- [conda-pack API](https://conda.github.io/conda-pack/api.html)
- [Linux `openat2(2)`](https://man7.org/linux/man-pages/man2/openat2.2.html)
- [Linux `write(2)`](https://man7.org/linux/man-pages/man2/write.2.html)
- [Linux `pread`/`pwrite(2)`](https://man7.org/linux/man-pages/man2/pread.2.html)
- [Linux `fsync(2)`](https://man7.org/linux/man-pages/man2/fsync.2.html)
- [Linux `close(2)`](https://man7.org/linux/man-pages/man2/close.2.html)
- [Linux ACLs](https://man7.org/linux/man-pages/man5/acl.5.html)
- [Linux xattrs](https://man7.org/linux/man-pages/man7/xattr.7.html)
- [CPython bytes C API](https://docs.python.org/3.12/c-api/bytes.html)
- [CPython buffer protocol](https://docs.python.org/3.12/c-api/buffer.html)
- [CPython Stable ABI](https://docs.python.org/3/c-api/stable.html)
- [GitHub artifact attestations](https://docs.github.com/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-to-establish-provenance-for-builds)
- [SLSA build provenance](https://slsa.dev/spec/v1.2/build-provenance)
- [Ferrite crash-consistency model](https://jamesbornholt.com/papers/ferrite-asplos16.pdf)

## Rerun inputs

```text
workflow: firecrawl-deep-research
topic: choose the highest-value next H2OMeta Agent-first slice by comparing a
  snapshot-derived Agent observation, a dormant regular-file capsule,
  relocation-free conda artifacts, journal/orchestrator semantics, metadata
  policy, fresh trusted-root verification, and native supply-chain wiring
depth: exhaustive (no time limit)
source preference: official specifications, primary documentation, source code,
  and peer-reviewed systems research
output: cited markdown decision report with contrarian findings, stop conditions,
  open questions, and a staged implementation recommendation
```
