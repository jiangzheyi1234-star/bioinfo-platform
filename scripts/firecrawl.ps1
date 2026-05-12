$ErrorActionPreference = "Stop"

if (-not (Get-Command npx -ErrorAction SilentlyContinue)) {
  throw "npx was not found. Install Node.js/npm before using the Firecrawl CLI wrapper."
}

if (-not $env:FIRECRAWL_NO_TELEMETRY) {
  $env:FIRECRAWL_NO_TELEMETRY = "1"
}

$cliArgs = @("-y", "firecrawl-cli@latest") + $args
& npx @cliArgs
exit $LASTEXITCODE
