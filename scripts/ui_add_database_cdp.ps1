param(
  [Parameter(Mandatory = $true)][string]$Template,
  [Parameter(Mandatory = $true)][string]$Path,
  [string]$Url = "http://127.0.0.1:3100/workflows/databases",
  [int]$Port = 9223
)

$ErrorActionPreference = "Stop"

function Send-CdpJson {
  param([string]$WebSocketUrl, [hashtable]$Payload)
  $ws = [System.Net.WebSockets.ClientWebSocket]::new()
  $uri = [Uri]$WebSocketUrl
  $ws.ConnectAsync($uri, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
  try {
    $json = $Payload | ConvertTo-Json -Depth 20 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $segment = [ArraySegment[byte]]::new($bytes)
    $ws.SendAsync($segment, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, [Threading.CancellationToken]::None).GetAwaiter().GetResult()

    $buffer = New-Object byte[] 1048576
    $stream = [System.IO.MemoryStream]::new()
    do {
      $recvSegment = [ArraySegment[byte]]::new($buffer)
      $result = $ws.ReceiveAsync($recvSegment, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
      if ($result.Count -gt 0) {
        $stream.Write($buffer, 0, $result.Count)
      }
    } while (-not $result.EndOfMessage)
    return [System.Text.Encoding]::UTF8.GetString($stream.ToArray()) | ConvertFrom-Json
  } finally {
    $ws.Dispose()
  }
}

$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
if (-not (Test-Path $chrome)) {
  $chrome = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
}
if (-not (Test-Path $chrome)) {
  throw "Chrome/Edge executable not found"
}

$userData = Join-Path $env:TEMP "h2ometa-cdp-profile"
New-Item -ItemType Directory -Force -Path $userData | Out-Null
$debugEndpoint = "http://127.0.0.1:$Port/json"

try {
  Invoke-RestMethod -Uri $debugEndpoint -TimeoutSec 1 | Out-Null
} catch {
  Start-Process -FilePath $chrome -ArgumentList @(
    "--remote-debugging-port=$Port",
    "--user-data-dir=$userData",
    "--no-first-run",
    "--new-window",
    $Url
  ) | Out-Null
  Start-Sleep -Seconds 3
}

$pages = Invoke-RestMethod -Uri $debugEndpoint -TimeoutSec 5
$page = @($pages | Where-Object { $_.type -eq "page" -and $_.url -like "http://127.0.0.1:3100/*" } | Select-Object -First 1)[0]
if (-not $page) {
  $newPage = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/new?$([uri]::EscapeDataString($Url))" -TimeoutSec 5
  $page = $newPage
  Start-Sleep -Seconds 2
}

$templateJson = $Template | ConvertTo-Json -Compress
$pathJson = $Path | ConvertTo-Json -Compress
$expression = @"
(async () => {
  const templateName = $templateJson;
  const databasePath = $pathJson;
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const buttons = () => Array.from(document.querySelectorAll('button'));
  const clickText = (text) => {
    const button = buttons().find((item) => (item.textContent || '').includes(text));
    if (!button) throw new Error('button not found: ' + text);
    button.scrollIntoView({ block: 'center', inline: 'center' });
    button.click();
    return button;
  };
  if (!document.querySelector('#database-path')) {
    clickText('\u6dfb\u52a0\u6570\u636e\u5e93');
    await wait(800);
  }
  const templateButton = buttons().find((item) => (item.textContent || '').includes(templateName));
  if (!templateButton) throw new Error('template not found: ' + templateName);
  templateButton.scrollIntoView({ block: 'center', inline: 'center' });
  await wait(200);
  templateButton.click();
  await wait(200);
  const input = document.querySelector('#database-path');
  if (!input) throw new Error('database path input not found');
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(input, databasePath);
  input.dispatchEvent(new Event('input', { bubbles: true }));
  await wait(200);
  clickText('\u52a0\u5165');
  await wait(500);
  return { templateName, databasePath, ok: true };
})()
"@

$payload = @{
  id = 1
  method = "Runtime.evaluate"
  params = @{
    expression = $expression
    awaitPromise = $true
    returnByValue = $true
  }
}

$response = Send-CdpJson -WebSocketUrl $page.webSocketDebuggerUrl -Payload $payload
if ($response.error) {
  throw ($response.error | ConvertTo-Json -Compress)
}
if ($response.result.exceptionDetails) {
  throw ($response.result.exceptionDetails | ConvertTo-Json -Depth 10 -Compress)
}
$response.result.result.value | ConvertTo-Json -Compress
