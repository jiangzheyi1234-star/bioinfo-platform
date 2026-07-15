function Assert-FirstRunScenarioToolSlice {
    param([object]$Pack, [string]$ExpectedContractState)
    $tools = @($Pack.requiredWorkflowReadyTools)
    if ($tools.Count -lt 3 -or $tools.Count -gt 5) {
        Fail-Pilot "$($Pack.scenarioId) must expose a 3-5 WorkflowReady tool slice"
    }
    if ($Pack.toolSliceHandoff.requiredState -ne "WorkflowReady" -or $Pack.toolSliceHandoff.noAutomaticExecution -ne $true) {
        Fail-Pilot "$($Pack.scenarioId) tool slice handoff must require WorkflowReady without automatic execution"
    }
    foreach ($tool in $tools) {
        if ($tool.contractState -ne $ExpectedContractState) {
            Fail-Pilot "$($Pack.scenarioId) tool $($tool.toolId) contractState must be $ExpectedContractState"
        }
        if (-not $tool.toolId -or ([string]$tool.toolId).ToLowerInvariant().Contains("bioconda")) {
            Fail-Pilot "$($Pack.scenarioId) tool slice must name curated tools instead of generic Bioconda imports"
        }
    }
}

function Assert-FirstRunBlockedScenarioPack {
    param([object]$Pack)
    if ($Pack.status -ne "blocked" -or $Pack.operatorActionRequired -ne $true) {
        Fail-Pilot "$($Pack.scenarioId) must stay blocked until operator gates pass"
    }
    if ($Pack.workflowPath -or $Pack.noAutomaticExecution -ne $true) {
        Fail-Pilot "$($Pack.scenarioId) must not expose automatic first-run execution"
    }
    Assert-FirstRunScenarioToolSlice $Pack "planned"
    if (@($Pack.readinessChecks | Where-Object { $_.status -eq "blocked" }).Count -lt 3) {
        Fail-Pilot "$($Pack.scenarioId) must expose blocked tool/sample/database readiness checks"
    }
    if ($Pack.databaseHandoff.mode -ne "manual_external" -or $Pack.databaseHandoff.noAutomaticExecution -ne $true) {
        Fail-Pilot "$($Pack.scenarioId) database handoff must stay manual_external without automatic execution"
    }
    if ($Pack.databaseHandoff.readyScan.path -ne "/api/v1/database-pack-ready-scans" -or $Pack.databaseHandoff.readyScan.mutatesRegistry -ne $false) {
        Fail-Pilot "$($Pack.scenarioId) database handoff must use a read-only ready scan before registration"
    }
    if (-not (@($Pack.resultEvidence) -contains "evidenceBundle")) {
        Fail-Pilot "$($Pack.scenarioId) pilot result evidence must include evidenceBundle"
    }
    if (-not (@($Pack.nextActions) | Where-Object { $_.target -like "/workflows*" })) {
        Fail-Pilot "$($Pack.scenarioId) must expose workflow-scoped next actions"
    }
}

function Assert-FirstRunScenarioPackCatalog {
    param([string]$ApiBase, [string]$FirstRunScenarioId, [string[]]$RequiredEvidence)
    $packs = Get-Json "$ApiBase/api/v1/workflow-scenario-packs"
    Assert-ArrayData $packs "workflow scenario packs"
    $items = @($packs.data.items)
    foreach ($scenarioId in @("moving-pictures-16s", "taxonomy-classification", "amr-annotation")) {
        if (-not (@($items | Where-Object { $_.scenarioId -eq $scenarioId }) | Select-Object -First 1)) {
            Fail-Pilot "workflow scenario packs must include $scenarioId"
        }
    }
    $pack = @($items | Where-Object { $_.scenarioId -eq $FirstRunScenarioId }) | Select-Object -First 1
    $expectedWorkflowPath = "/workflows/detail?workflow=$($pack.pipelineId)"
    if ($pack.status -ne "ready" -or $pack.workflowPath -ne $expectedWorkflowPath) {
        Fail-Pilot "$FirstRunScenarioId must be ready and point at its workflow detail page"
    }
    Assert-FirstRunScenarioToolSlice $pack "workflow_ready"
    foreach ($evidence in $RequiredEvidence) {
        if ($pack.resultEvidence -notcontains $evidence) {
            Fail-Pilot "$FirstRunScenarioId resultEvidence missing $evidence"
        }
    }
    foreach ($scenarioId in @("taxonomy-classification", "amr-annotation")) {
        $scenario = @($items | Where-Object { $_.scenarioId -eq $scenarioId }) | Select-Object -First 1
        Assert-FirstRunBlockedScenarioPack $scenario
    }
    return $pack
}
