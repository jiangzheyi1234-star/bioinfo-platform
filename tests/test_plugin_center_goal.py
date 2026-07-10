from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"
CORE_RUNTIME = ROOT / "core" / "app_runtime"
PLUGIN_ROUTE = ROOT / "apps" / "web" / "app" / "workflows" / "plugins" / "page.tsx"
ROADMAP = ROOT / "docs" / "roadmaps" / "plugin-extension-center-goal.md"


def test_plugin_center_goal_document_defines_boundaries_and_phases() -> None:
    source = ROADMAP.read_text(encoding="utf-8")

    assert "SSH is the connection channel, not the plugin" in source
    assert "Remote provisioning job" in source
    assert "tool preparation and remote executor provisioning into one backend domain model" in source
    assert "### Phase 1: Navigation And Goal Surface" in source
    assert "### Phase 3: Local Provisioning Job Contract" in source
    assert "### Phase 4: First-Class Server Profiles" in source
    assert "The optional thin CLI should be a management shell around the service" in source


def test_plugin_center_route_surfaces_phase_one_cards() -> None:
    route_source = PLUGIN_ROUTE.read_text(encoding="utf-8")
    page_source = (COMPONENTS / "plugin-center-page.tsx").read_text(encoding="utf-8")
    manager_source = (COMPONENTS / "plugin-center-extension-manager.tsx").read_text(encoding="utf-8")
    model_source = (COMPONENTS / "plugin-center-model.ts").read_text(encoding="utf-8")
    sidebar_source = (COMPONENTS / "ssh-shell-ui.tsx").read_text(encoding="utf-8")

    assert "PluginCenterPage" in route_source
    assert "PluginCenterExtensionManager" in page_source
    assert 'data-testid="plugin-center-page"' in manager_source
    assert 'data-testid="plugin-center-search"' in manager_source
    assert 'data-testid="plugin-center-installed-strip"' in manager_source
    assert 'data-testid="plugin-center-source-tabs"' in manager_source
    assert 'data-testid="plugin-center-installation-tasks-card"' in manager_source
    assert "PLUGIN_CENTER_VIEW_MODES" in model_source
    assert "PluginCenterExtensionItem" in model_source
    assert "PluginCenterTask" in model_source
    assert "useWorkflowRunnerRepairState" in page_source
    assert "RunnerRepairPanel" in page_source
    assert "PluginCenterExtensionManifest" in model_source
    assert 'Link href="/workflows/plugins"' in sidebar_source
    assert "pluginsActive" in sidebar_source


def test_plugin_center_remote_executor_flow_uses_existing_trust_and_repair_paths() -> None:
    page_source = (COMPONENTS / "plugin-center-page.tsx").read_text(encoding="utf-8")
    manager_source = (COMPONENTS / "plugin-center-extension-manager.tsx").read_text(encoding="utf-8")
    details_source = (COMPONENTS / "plugin-center-extension-details.tsx").read_text(encoding="utf-8")
    repair_source = (COMPONENTS / "ssh-runner-repair-panel.tsx").read_text(encoding="utf-8")
    connection_source = (COMPONENTS / "ssh-shell-connection.ts").read_text(encoding="utf-8")
    registry_source = (CORE_RUNTIME / "managed_extension_registry.py").read_text(encoding="utf-8")

    assert "useSshShell()" in page_source
    assert "sshShell.setDialogOpen(true)" in page_source
    assert "sshShell.setForm(toForm(sshShell.status))" in page_source
    assert "mergePluginRemoteStatus" in page_source
    assert "rawStatus = runnerRepair.status || sshShell.status" in page_source
    assert "executePluginCenterExtensionAction" in page_source
    assert "openExtensionDetails(item, item.primaryAction)" in page_source
    assert "executeExtensionAction(item, item.primaryAction)" not in page_source
    assert "PluginCenterExtensionDetails" in page_source
    assert "onActionConfirm" in details_source
    assert "onPrimaryAction(item)" in manager_source
    assert "onExtensionAction(item, action.id)" in manager_source
    assert 'catalog_extra={"manageHref": "#remote-runner-detail"}' in registry_source
    assert 'item.primaryAction === "manage" && item.manageHref' in manager_source
    assert '"h2ometa-remote-runner"' not in page_source
    assert '"repair"' in page_source
    assert "RunnerRepairPanel" in page_source
    assert "status?.connected ? (" in page_source
    assert "/runner/upgrade" in repair_source
    assert "/operator-diagnostics" in repair_source
    assert "/runner/releases/prune/preview" in repair_source
    assert "/runner/uninstall/preview" in repair_source
    assert "/api/v1/ssh/host-key/scan" in connection_source
    assert "/host-key/accept" in connection_source
    assert 'confirmation: "trust-ssh-host-key"' in connection_source


def test_plugin_center_phase_three_uses_local_remote_provisioning_jobs() -> None:
    page_source = (COMPONENTS / "plugin-center-page.tsx").read_text(encoding="utf-8")
    api_source = (COMPONENTS / "plugin-center-api.ts").read_text(encoding="utf-8")
    model_source = (COMPONENTS / "plugin-center-model.ts").read_text(encoding="utf-8")
    manager_source = (COMPONENTS / "plugin-center-extension-manager.tsx").read_text(encoding="utf-8")
    view_model_source = (COMPONENTS / "plugin-center-view-model.ts").read_text(encoding="utf-8")
    route_source = (API / "ssh_routes.py").read_text(encoding="utf-8")
    control_source = (API / "ssh_control_service.py").read_text(encoding="utf-8")
    runtime_source = (CORE_RUNTIME / "remote_provisioning_jobs.py").read_text(encoding="utf-8")
    service_source = (CORE_RUNTIME / "service.py").read_text(encoding="utf-8")

    assert "executePluginCenterExtensionAction" in page_source
    assert "fetchRemoteProvisioningJobQueue" in page_source
    assert "activeRunnerProvisioningJob" in page_source
    assert "buildPluginCenterTasks" in page_source
    assert 'kind: "remote-provisioning"' in view_model_source
    assert 'data-testid="plugin-center-installation-tasks-card"' in manager_source
    assert "/api/v1/plugin-center/extensions/${encodeURIComponent(extensionId)}/actions" in api_source
    assert "createRemoteProvisioningJob" not in api_source
    assert "/api/v1/remote-provisioning/jobs?" in api_source
    assert "REMOTE_PROVISIONING_ACTIVE_STATUSES" in model_source
    assert "RemoteProvisioningJobQueue" in model_source
    assert '"repair-runner"' in model_source
    assert '"/api/v1/servers/{server_id}/remote-provisioning/jobs"' in route_source
    assert '"/api/v1/servers/{server_id}/runner/diagnostics/repair"' in route_source
    assert '"/api/v1/remote-provisioning/jobs"' in route_source
    assert '"/api/v1/remote-provisioning/jobs/{job_id}/cancel"' in route_source
    assert "create_remote_provisioning_job_from_request" in control_source
    assert "list_remote_provisioning_job_queue_from_request" in control_source
    assert "class RemoteProvisioningOperationsMixin" in runtime_source
    assert "REMOTE_PROVISIONING_CONFIG_KEY" in runtime_source
    assert "threading.Thread" in runtime_source
    assert "RemoteProvisioningOperationsMixin" in service_source


def test_plugin_center_phase_four_surfaces_server_profiles() -> None:
    page_source = (COMPONENTS / "plugin-center-page.tsx").read_text(encoding="utf-8")
    api_source = (COMPONENTS / "plugin-center-api.ts").read_text(encoding="utf-8")
    model_source = (COMPONENTS / "plugin-center-model.ts").read_text(encoding="utf-8")
    route_source = (API / "ssh_routes.py").read_text(encoding="utf-8")
    runtime_source = (CORE_RUNTIME / "server_profiles.py").read_text(encoding="utf-8")
    service_source = (CORE_RUNTIME / "service.py").read_text(encoding="utf-8")

    assert "fetchServerProfiles" in page_source
    assert "activeServerProfile" in page_source
    assert "/api/v1/server-profiles" in api_source
    assert "type ServerProfile" in model_source
    assert '"/api/v1/server-profiles"' in route_source
    assert "SERVER_PROFILES_CONFIG_KEY" in runtime_source
    assert "DEFAULT_SERVER_PROFILE_ID" in runtime_source
    assert "_provisioning_projection" in runtime_source
    assert "_diagnostics_projection" in runtime_source
    assert "last_provisioning_job_id" in runtime_source
    assert "last_diagnostics_bundle_ref" in runtime_source
    assert "ServerProfileOperationsMixin" in service_source


def test_plugin_center_phase_five_aggregates_extension_tasks_without_merging_domains() -> None:
    page_source = (COMPONENTS / "plugin-center-page.tsx").read_text(encoding="utf-8")
    view_model_source = (COMPONENTS / "plugin-center-view-model.ts").read_text(encoding="utf-8")
    manager_source = (COMPONENTS / "plugin-center-extension-manager.tsx").read_text(encoding="utf-8")
    roadmap_source = ROADMAP.read_text(encoding="utf-8")

    assert "fetchToolPrepareJobQueue" in page_source
    assert "TOOL_PREPARE_ACTIVE_STATUSES" in page_source
    assert "toolPrepareActiveCount" in page_source
    assert "buildPluginCenterTasks(provisioningQueue, toolPrepareQueue)" in page_source
    assert 'kind: "tool-prepare"' in view_model_source
    assert "TOOL_PREPARE_ACTIVE_STATUSES.includes" in view_model_source
    assert 'data-testid="plugin-center-installation-tasks-card"' in manager_source
    assert "tool preparation stays remote-runner owned" in roadmap_source
    assert "remote provisioning queue separately" in roadmap_source


def test_plugin_center_phase_six_uses_backend_managed_extension_registry() -> None:
    page_source = (COMPONENTS / "plugin-center-page.tsx").read_text(encoding="utf-8")
    api_source = (COMPONENTS / "plugin-center-api.ts").read_text(encoding="utf-8")
    model_source = (COMPONENTS / "plugin-center-model.ts").read_text(encoding="utf-8")
    route_source = (API / "plugin_center_routes.py").read_text(encoding="utf-8")
    route_service_source = (API / "plugin_center_service.py").read_text(encoding="utf-8")
    runtime_source = (CORE_RUNTIME / "managed_extensions.py").read_text(encoding="utf-8")
    registry_source = (CORE_RUNTIME / "managed_extension_registry.py").read_text(encoding="utf-8")
    contract_source = (ROOT / "core" / "contracts" / "managed_extensions.py").read_text(encoding="utf-8")
    service_source = (CORE_RUNTIME / "service.py").read_text(encoding="utf-8")
    main_source = (API / "main.py").read_text(encoding="utf-8")

    assert "fetchPluginCenterExtensions" in api_source
    assert '"/api/v1/plugin-center/extensions"' in api_source
    assert "PluginCenterExtensionList" in model_source
    assert "PluginCenterExtensionActionRequest" in model_source
    assert "managedExtensionList" in page_source
    assert "managedExtensionList?.items || []" in page_source
    assert "buildPluginCenterExtensions" not in page_source
    assert '"/api/v1/plugin-center/extensions"' in route_source
    assert '"/api/v1/plugin-center/extensions/{extension_id}/actions"' in route_source
    assert "list_plugin_center_extensions_from_request" in route_source
    assert "execute_plugin_center_extension_action_from_request" in route_source
    assert "runtime_service().list_managed_extensions" in route_service_source
    assert "runtime_service().execute_managed_extension_action" in route_service_source
    assert "class ManagedExtensionOperationsMixin" in runtime_source
    assert "MANAGED_EXTENSION_MANIFEST_SCHEMA_VERSION" in contract_source
    assert "MANAGED_EXTENSION_ACTION_RESULT_SCHEMA_VERSION" in runtime_source
    assert "REMOTE_EXECUTOR_EXTENSION_ID" not in runtime_source
    assert '"h2ometa-remote-runner"' not in runtime_source
    assert "REMOTE_RUNNER_ARTIFACT" in registry_source
    assert "release_artifact_distribution" in registry_source
    assert "ManagedExtensionDriverRegistry" in runtime_source
    assert "execute_managed_extension_action" in runtime_source
    assert "ManagedExtensionOperationsMixin" in service_source
    assert "plugin_center_router" in main_source


def test_plugin_center_phase_seven_removes_frontend_extension_fallback() -> None:
    page_source = (COMPONENTS / "plugin-center-page.tsx").read_text(encoding="utf-8")
    view_model_source = (COMPONENTS / "plugin-center-view-model.ts").read_text(encoding="utf-8")
    manager_source = (COMPONENTS / "plugin-center-extension-manager.tsx").read_text(encoding="utf-8")

    assert "buildPluginCenterExtensions" not in page_source
    assert "function buildPluginCenterExtensions" not in view_model_source
    assert "type BuildPluginCenterExtensionsInput" not in view_model_source
    assert "loadError" in manager_source
    assert "extensionActionOptions" in manager_source
    assert "managed-extension-action" in manager_source


def test_plugin_center_v2_details_preflight_and_resilient_loading_contract() -> None:
    page_source = (COMPONENTS / "plugin-center-page.tsx").read_text(encoding="utf-8")
    manager_source = (COMPONENTS / "plugin-center-extension-manager.tsx").read_text(encoding="utf-8")
    details_source = (COMPONENTS / "plugin-center-extension-details.tsx").read_text(encoding="utf-8")
    model_source = (COMPONENTS / "plugin-center-model.ts").read_text(encoding="utf-8")

    assert 'schemaVersion: "h2ometa.managed-extension-manifest.v2"' in model_source
    assert "registryId: string" in model_source
    assert "version: string" in model_source
    assert "registries: PluginCenterRegistry[]" in model_source
    assert "packageImport: boolean" in model_source
    assert "placement: PluginCenterPlacement" in model_source
    assert "installTargets: PluginCenterInstallTarget[]" in model_source
    assert "distribution: PluginCenterDistribution" in model_source
    assert "compatibility: PluginCenterCompatibility" in model_source
    assert "capabilities: PluginCenterCapability[]" in model_source
    assert "driver: string" in model_source
    assert "signatureAvailable: boolean" in model_source

    assert 'const PREFLIGHT_ACTIONS = new Set(["install", "repair", "update"])' in page_source
    assert "openExtensionDetails(item, item.primaryAction)" in page_source
    assert "confirmExtensionAction" in page_source
    assert "hostKeyTrust.trusted" in page_source
    assert "status?.connected || activeServerProfile?.connected || activeServerProfile?.hostKeyTrust.trusted" not in page_source
    assert "expectedServerId" in page_source
    assert "远端目标已变化" in page_source
    assert "declaredAction.requiresConfirmation" in page_source
    assert '"h2ometa-remote-runner"' not in page_source
    assert 'mode: "preview"' in page_source
    assert "planHash" in page_source
    assert "setManagedExtensionList(null)" not in page_source
    assert "refreshManagedExtensions(undefined, true)" in page_source

    assert "manifest.distribution.variants" in details_source
    assert "SHA-256" in details_source
    assert "SBOM" in details_source
    assert "Provenance" in details_source
    assert "Attestation" in details_source
    assert "Signature" in details_source
    assert "Host key" in details_source
    assert "trustMissing" in details_source
    assert "confirmationKey" in details_source
    assert "targetServerId: string" in details_source
    assert "metadata available" in details_source
    assert "不代表签名、证明或制品已经通过安装策略验证" in details_source
    assert "manifest.permissions" in details_source
    assert "manifest.capabilities" in details_source

    assert 'aria-live="assertive"' in manager_source
    assert 'role="tab"' in manager_source
    assert 'type="search"' in manager_source
    assert 'id: "installed"' in manager_source
    assert 'id: "updates"' in manager_source
    assert 'id: "attention"' in manager_source
    assert 'item.updateAvailable === true' in manager_source
    assert "onOpenDetails" in manager_source
    assert "当前保留并显示上次成功加载的数据" in manager_source
    assert "本地包安装" not in manager_source
    assert "本地包安装" not in details_source
    assert "try_in_chat" not in page_source
