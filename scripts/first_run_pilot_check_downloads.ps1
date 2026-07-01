function Normalize-FirstRunHash {
    param([object]$Value)
    return ([string]$Value).Trim().ToLowerInvariant()
}

function Get-FirstRunResponseHeader {
    param([object]$Response, [string]$Name)
    if ($null -eq $Response -or $null -eq $Response.Headers) {
        return ""
    }
    foreach ($key in $Response.Headers.Keys) {
        if ([string]::Equals([string]$key, $Name, [System.StringComparison]::OrdinalIgnoreCase)) {
            return [string](@($Response.Headers[$key]) | Select-Object -First 1)
        }
    }
    return ""
}

function Assert-FirstRunResultPackageDownload {
    param([object]$Package, [object]$ResultPackageFile)
    if ($null -eq $ResultPackageFile -or [string]::IsNullOrWhiteSpace([string]$ResultPackageFile.href)) {
        Fail-Pilot "first-run result package download href must be present"
    }
    if (-not ([string]$ResultPackageFile.href).StartsWith("/api/v1/results/")) {
        Fail-Pilot "first-run result package download href must stay under the result package download API"
    }
    $expectedFilename = [string]$Package.download.filename
    if ($expectedFilename -and $ResultPackageFile.filename -ne $expectedFilename) {
        Fail-Pilot "first-run result package download filename must match package metadata"
    }
    $expectedSha256 = Normalize-FirstRunHash $Package.sha256
    $expectedFileSha256 = Normalize-FirstRunHash $ResultPackageFile.sha256
    $expectedManifestSha256 = Normalize-FirstRunHash $Package.manifestSha256
    $packagePath = Join-Path ([System.IO.Path]::GetTempPath()) "h2ometa-first-run-result-package-$([guid]::NewGuid().ToString('N')).zip"
    $sizeBytes = 0
    $actualSha256 = ""
    $headerSha256 = ""
    $headerManifestSha256 = ""
    try {
        $downloadUrl = "$($ApiBase.TrimEnd("/"))$($ResultPackageFile.href)"
        $response = Invoke-WebRequest -Uri $downloadUrl -UseBasicParsing -OutFile $packagePath -TimeoutSec $TimeoutSeconds
        $packageItem = Get-Item -LiteralPath $packagePath
        $sizeBytes = $packageItem.Length
        if ($sizeBytes -le 0) { throw "downloaded result package is empty" }
        $actualSha256 = Normalize-FirstRunHash (Get-FileHash -Algorithm SHA256 -LiteralPath $packagePath).Hash
        if ($actualSha256 -ne $expectedSha256 -or $actualSha256 -ne $expectedFileSha256) {
            throw "downloaded result package SHA-256 does not match finalization evidence"
        }
        $headerSha256 = Normalize-FirstRunHash (Get-FirstRunResponseHeader $response "x-h2ometa-sha256")
        $headerManifestSha256 = Normalize-FirstRunHash (Get-FirstRunResponseHeader $response "x-h2ometa-manifest-sha256")
        if ($headerSha256 -and $headerSha256 -ne $actualSha256) {
            throw "result package SHA-256 header does not match downloaded bytes"
        }
        if ($headerManifestSha256 -and $headerManifestSha256 -ne $expectedManifestSha256) {
            throw "result package manifest SHA-256 header does not match finalization evidence"
        }
    } catch {
        Fail-Pilot "first-run result package download validation failed: $($_.Exception.Message)"
    } finally {
        if (Test-Path -LiteralPath $packagePath) { Remove-Item -LiteralPath $packagePath -Force }
    }
    return [ordered]@{
        filename = $ResultPackageFile.filename
        href = $ResultPackageFile.href
        sizeBytes = $sizeBytes
        sha256 = $actualSha256
        headerSha256 = $headerSha256
        headerManifestSha256 = $headerManifestSha256
    }
}

function Assert-FirstRunEvidenceBundleDownload {
    param([object]$Bundle, [object]$Evidence, [object]$Card)
    $download = $Bundle.download
    if ($null -eq $download) {
        Fail-Pilot "first-run evidenceBundle must expose an evidence-bundle ZIP download"
    }
    if ($download.role -ne "evidence-bundle-zip" -or $download.source -ne "first-run-evidence-bundle-zip-api") {
        Fail-Pilot "first-run evidenceBundle ZIP download must use the explicit evidence-bundle-zip role and source"
    }
    $baseName = $Card.result.resultId
    $expectedFilename = "$baseName.first-run-evidence.zip"
    if ($download.filename -ne $expectedFilename) {
        Fail-Pilot "first-run evidenceBundle ZIP filename must be $expectedFilename"
    }
    $expectedServerQuery = ""
    if ($Card.runner.serverId) {
        $expectedServerQuery = "?serverId=$([uri]::EscapeDataString($Card.runner.serverId))"
    }
    $expectedHref = "/api/v1/first-run/runs/$([uri]::EscapeDataString($Evidence.runId))/evidence-bundle.zip$expectedServerQuery"
    if ($download.href -ne $expectedHref) {
        Fail-Pilot "first-run evidenceBundle ZIP href must be $expectedHref"
    }
    if (-not ([string]$download.href).StartsWith("/api/v1/first-run/runs/")) {
        Fail-Pilot "first-run evidenceBundle ZIP href must stay under the first-run download API"
    }

    $zipPath = Join-Path ([System.IO.Path]::GetTempPath()) "h2ometa-first-run-evidence-$([guid]::NewGuid().ToString('N')).zip"
    $archive = $null
    $entryNames = @()
    $zipSizeBytes = 0
    try {
        $downloadUrl = "$($ApiBase.TrimEnd("/"))$($download.href)"
        Invoke-WebRequest -Uri $downloadUrl -UseBasicParsing -OutFile $zipPath -TimeoutSec $TimeoutSeconds | Out-Null
        $zipItem = Get-Item -LiteralPath $zipPath
        $zipSizeBytes = $zipItem.Length
        if ($zipSizeBytes -le 0) { throw "downloaded ZIP is empty" }
        Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop
        $archive = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
        $entryNames = @($archive.Entries | ForEach-Object { $_.FullName })
        $expectedEntries = @("README.md", "$baseName.evidence-bundle.json", "$baseName.validation-card.json", "$baseName.validation-card.md", "$baseName.pilot-handoff.md")
        if ((@($entryNames | Sort-Object) -join "|") -ne (@($expectedEntries | Sort-Object) -join "|")) {
            throw "ZIP entries must exactly match the portable first-run evidence files"
        }
        foreach ($entryName in $expectedEntries) {
            $entry = @($archive.Entries | Where-Object { $_.FullName -eq $entryName }) | Select-Object -First 1
            if ($null -eq $entry -or $entry.Length -le 0) {
                throw "ZIP entry $entryName must be present and non-empty"
            }
        }
    } catch {
        Fail-Pilot "first-run evidenceBundle ZIP download validation failed: $($_.Exception.Message)"
    } finally {
        if ($null -ne $archive) { $archive.Dispose() }
        if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    }
    return [ordered]@{
        role = $download.role
        source = $download.source
        filename = $download.filename
        href = $download.href
        zipSizeBytes = $zipSizeBytes
        entryNames = @($entryNames | Sort-Object)
    }
}
