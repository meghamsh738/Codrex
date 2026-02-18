param(
  [int]$Port = 8787
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSCommandPath
$startScript = Join-Path $root "start-controller.ps1"
$configPath = Join-Path $root "controller.config.json"
$logsDir = Join-Path $root "logs"
$logPath = Join-Path $logsDir "watchdog.log"

if (-not (Test-Path $startScript)) {
  throw "Missing start script at $startScript"
}
if (-not (Test-Path $logsDir)) {
  New-Item -Path $logsDir -ItemType Directory -Force | Out-Null
}

if (Test-Path $configPath) {
  try {
    $cfg = Get-Content $configPath -Raw | ConvertFrom-Json
    if ($cfg -and $cfg.port) {
      $Port = [int]$cfg.port
    }
  } catch {}
}

$healthy = $false
try {
  $resp = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/auth/status" -TimeoutSec 2
  if ($resp.StatusCode -eq 200) {
    $healthy = $true
  }
} catch {}

if ($healthy) {
  exit 0
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $logPath -Value "$stamp unhealthy on port $Port, restarting"

try {
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startScript -Port $Port | Out-Null
  $done = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  Add-Content -Path $logPath -Value "$done restart command completed"
} catch {
  $fail = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  Add-Content -Path $logPath -Value "$fail restart failed: $($_.Exception.Message)"
  throw
}
