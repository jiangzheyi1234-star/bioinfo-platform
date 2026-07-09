# Plugin And Remote Executor Goal

Status: Phased implementation; Phase 1-5 baselines landed, broad multi-profile UX and richer runtime packs pending

Last reviewed: 2026-07-08

## Objective

Create a clear plugin and extension center for H2OMeta. The left sidebar should expose a first-class `Plugins` or `Extensions` entry where users can install and manage the remote executor, tool plugins, and runtime components through one consistent installation mental model.

The first product milestone is the remote executor installation experience:

```text
Plugins / Extensions
  -> Remote executor card
  -> SSH server profile and host-key trust
  -> Remote provisioning job
  -> Versioned remote runner service
  -> Health, canary, repair, upgrade, and uninstall controls
```

SSH is the connection channel, not the plugin. The installable plugin-like unit is the H2OMeta remote executor, backed by the existing long-running remote runner service.

## Why Now

The repository already has most of the hard infrastructure for remote execution:

- SSH connection, host-key scan, host-key trust, password/key/agent/ssh-config auth, and startup auto-connect.
- Manifest-declared remote runner artifacts, versioned remote layout, install locks, upload, activation, health checks, canary validation, rollback, token storage, token rotation, release pruning, and uninstall.
- A remote FastAPI runner service with workflow, tool, database, artifact, trigger, audit, and secret routes plus worker supervisors.
- A tool preparation task bar with polling, task stages, event logs, cancellation, and recovery patterns.

The current product shape hides these capabilities behind the SSH status area and repair panel. A plugin center makes the product model simpler: connect to a server, install the remote executor, then install or prepare analysis capabilities on that executor.

## Product Principles

1. Make the first screen an operational center, not a marketing page.
2. Keep SSH visible as trust and connectivity, but do not call SSH itself a plugin.
3. Treat the remote executor as a managed extension with install, reuse, repair, upgrade, stop, token rotation, diagnostics, and uninstall.
4. Reuse the existing task-bar language for installation progress: stages, current action, event log, failure reason, and retry action.
5. Keep dangerous actions explicit. Host-key trust, destructive cleanup, uninstall, release prune, token rotation, and replacing an existing runner require confirmation.
6. Fail loudly when an unsupported state is found. Do not silently fall back to legacy behavior or source checkouts.
7. Preserve the current remote-agent strategy: versioned artifacts, immutable releases, shared mutable data, health gates, canary proof, and rollback.

## Non-Goals

This goal does not require a public plugin marketplace, multi-user SaaS hosting, public production deployment, Kubernetes, Postgres, a broad plugin SDK, or a rewrite of tool preparation.

This goal does not turn the remote runner into a pure one-shot CLI. A thin CLI may exist for service operations such as `status`, `start`, `stop`, `doctor`, and `uninstall`, but workflow execution and stateful APIs remain in the long-running remote runner service.

This goal does not merge tool preparation and remote executor provisioning into one backend domain model. Tool preparation belongs to an already-ready runner; remote executor provisioning belongs to the local SSH control plane.

## Architecture Direction

The target architecture is:

```text
apps/web plugin center
  -> apps/api local control routes
  -> first-class server profile
  -> local remote provisioning job
  -> SSH/SFTP bootstrap through core.remote_runner
  -> remote h2ometa-remote service
  -> SSH tunnel + bearer token
  -> remote endpoint contracts
```

The remote service remains the execution authority. The local app owns connection, trust, artifact resolution, provisioning progress, tunnel setup, and the operator-facing install lifecycle.

## Required Model Boundaries

### Server Profile

Add a first-class server profile model before broad multi-server UX. A profile should bind:

- Display name and stable server id.
- Host, port, user, auth mode, SSH config alias, identity reference, and remember/auto-connect preferences.
- Host-key trust state and accepted fingerprint.
- Runner token reference, runner version, service port, last tunnel projection, health snapshot, and install state.
- Last provisioning job id and last diagnostics bundle reference when available.

The current single global `ssh` config can remain as a compatibility source during the first slice, but new UI and contracts should move toward explicit server profiles.

### Remote Provisioning Job

Add a local control-plane job model for remote executor installation. It should follow the shape of tool preparation jobs but remain a separate domain:

```text
queued
running
succeeded
failed
cancelled
```

Each job should expose:

- `jobId`, `serverId`, `action`, `status`, `stage`, `message`, and timestamps.
- Stage events with stable codes and redacted details.
- Artifact version, artifact digest, remote platform, remote mode, workflow runtime version, install-lock state, runtime-state snapshot, tunnel port, health summary, canary summary, and rollback outcome when present.
- Poll and cancel endpoints.
- A final safe diagnostics summary.

### Remote Executor Service

Keep the remote executor as the existing long-running service. The service should continue to provide workflow execution, tool preparation, database registry, artifact handling, result packages, triggers, audit, and secret-provider readiness.

The optional thin CLI should be a management shell around the service, not the core execution model.

## UX Target

The left sidebar gets a new entry:

```text
Plugins
```

The first plugin center screen should include:

- Remote Executor card: current server, SSH trust state, runner readiness, installed version, action button, and diagnostics entry.
- Tool Plugins card: link to the current tools page and show active tool preparation tasks.
- Runtime Components card: managed workflow runtime, wrappers, and future database/runtime components.
- Installation Tasks area: active and recent install/provision/prepare jobs with progress and event details.

The global SSH/runner status bar should remain. It answers "what am I connected to right now?" The plugin center answers "what capabilities are installed or need attention?"

## Phases

### Phase 1: Navigation And Goal Surface

- Add a left-sidebar `Plugins` or `Extensions` entry.
- Add a plugin center route.
- Render the remote executor card from existing SSH/runner status.
- Link to current tool management.
- Reuse existing repair controls where possible.

Acceptance evidence:

- Sidebar structure test proves the entry exists.
- Route surface test proves the plugin center route exists.
- Component structure test proves the remote executor, tool plugins, runtime components, and task area are present.

### Phase 2: Install-Style Remote Executor Flow

- Wrap existing `ensure-runner`, `upgrade`, `start`, diagnostics, prune, and uninstall actions in plugin-center controls.
- Present connect, trust host key, install/reuse, canary, ready, and repair stages.
- Keep current SSH connect dialog and host-key confirmation path.

Acceptance evidence:

- Frontend contract test covers disconnected, SSH-connected, preparing, ready, repair-needed, stopped, and failed states.
- API contract test proves existing runner lifecycle endpoints still fail loudly with typed reasons.
- Manual UI smoke verifies stale local web processes were restarted before judging the UI.

### Phase 3: Local Provisioning Job Contract

- Add a local provisioning job store and API contract.
- Emit structured bootstrap stages from the current remote runner manager.
- Expose poll/cancel/detail endpoints.
- Surface job events in the plugin center task area.

Acceptance evidence:

- Unit tests cover job state transitions, cancellation, failure details, rollback details, and redaction.
- API route tests cover create, read, list, cancel, and stale/duplicate job behavior.
- Existing remote bootstrap tests still pass.

### Phase 4: First-Class Server Profiles

- Introduce explicit server profile records.
- Migrate current single SSH config into a default profile path without silently changing semantics.
- Bind runner registry state to profile identity.
- Prepare the UI for multiple profiles without requiring full multi-server switching in the first slice.

Baseline landed:

- The local API exposes a default server profile read model derived from the current SSH config plus server registry.
- The plugin center shows the active profile, host-key trust, and runner token binding summary.
- Host-key trust acceptance persists fingerprint and known-hosts metadata into the server registry for later profile reads.

Acceptance evidence:

- Config tests cover migration, keyring refs, known-host path, and token refs.
- SSH connection tests cover password, key file, ssh-config alias, and agent modes.
- No secrets are written to public diagnostics or committed config files.

### Phase 5: Unified Extension Center

- Bring tool plugins, runtime components, and database/runtime pack status into the plugin center.
- Keep source-of-truth boundaries separated: tool preparation stays remote-runner owned; remote provisioning stays local-control-plane owned.
- Add shared task presentation utilities only after duplication proves real.

Baseline landed:

- The plugin center reads the remote-runner owned tool prepare queue and local-control-plane owned remote provisioning queue separately.
- The installation task summary aggregates active tool preparation and remote provisioning counts without merging their backend domain models.
- The tool plugin card surfaces the latest remote tool preparation job when the runner is available, while keeping the existing tools page as the detailed management surface.
- The plugin center now uses a Codex-style unified extension manager layout with `插件` / `技能` tabs, global search, installed extension strip, source filters, category sections, and a shared installation task list.
- Runtime, tool, database, tool-pack, and skill entries are adapted into a shared frontend `PluginCenterExtensionItem` read model before introducing any new backend aggregation endpoint.
- Remote provisioning jobs and tool prepare jobs are adapted into a shared frontend `PluginCenterTask` view while preserving their separate backend owners.

Acceptance evidence:

- Tool prepare tests still cover tool-specific behavior.
- Plugin center tests verify cross-card status aggregation without leaking secrets.
- Documentation explains the ownership boundary.
- Browser smoke against a real local web session verifies the unified plugin manager shows the real server profile, remote runner version, workflow runtime version, source filters, category sections, and unified task list.

## Completion Criteria

The goal is complete when current-state evidence proves:

- The left sidebar has a stable plugin/extension entry.
- A plugin center route exists and is the primary place to manage remote executor installation state.
- The remote executor can be installed, reused, repaired, upgraded, stopped, diagnosed, and uninstalled from that surface or directly linked controls.
- Remote executor installation progress is represented as a job or equivalent persisted lifecycle with stages and events, not only a long blocking request.
- Server profiles are first-class enough to bind SSH identity, host-key trust, and runner state.
- Tool plugins and remote executor provisioning share UX patterns without sharing the same backend domain model.
- Security confirmations, token handling, host-key trust, redaction, rollback, and fail-closed behavior remain intact.
- Tests and documentation cover the route, UI states, API contracts, provisioning lifecycle, and security boundaries.

## Current Decisions And Deferred Choices

- Navigation uses the Chinese product label `插件` while the architecture vocabulary remains plugin/extension center.
- Tool management stays on the current tools page for detailed workflows; the plugin center links to it and reads the tool prepare queue for summary status.
- The plugin center page should remain a discovery, install, enable, update, and status surface. Specialized tool contract editing, database registration, and runner repair details may open linked deep-management surfaces instead of being duplicated inline.
- The first provisioning job store lives in the local runtime config. Moving it to local SQLite is deferred until retention, audit, or concurrency pressure proves the need.
- A backend plugin-center summary endpoint is deferred until the frontend read-model adapters become too complex or multi-profile loading requires server-side aggregation.
- The current single `ssh` config remains as the compatibility source while the API exposes a first-class default server profile projection.
- The thin remote CLI remains deferred. If added, it should be packaged as a management shell around the long-running service after provisioning lifecycle evidence is stable.

## Related Documents

- `docs/remote-agent-deployment-strategy.md`
- `docs/security-governance.md`
- `docs/snakemake-tool-integration-spec.md`
- `docs/codex-agent-fleet.md`
