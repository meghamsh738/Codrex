param(
  [int]$Port = 48787
)

$ErrorActionPreference = "Stop"

function Get-CodrexRuntimeDir {
  param(
    [string]$RepoRoot
  )
  $override = [string]$env:CODEX_RUNTIME_DIR
  if ($override -and $override.Trim()) {
    return $override.Trim()
  }
  $localAppData = [string]$env:LocalAppData
  if ($localAppData -and $localAppData.Trim()) {
    return (Join-Path $localAppData "Codrex\remote-ui")
  }
  return (Join-Path $RepoRoot ".runtime")
}

function Write-WatchdogBreadcrumb {
  param(
    [string]$Message
  )
  try {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
    Add-Content -Path $startupLogPath -Value "$stamp [watchdog-controller] $Message"
  } catch {}
}

function Test-RecentControllerStartup {
  if (-not (Test-Path $controllerStartupStatePath)) {
    return $false
  }
  try {
    $raw = Get-Content -Path $controllerStartupStatePath -Raw | ConvertFrom-Json
    $startedAt = Get-Date $raw.started_at
    $ageSeconds = ((Get-Date) - $startedAt).TotalSeconds
    if ($ageSeconds -le 90) {
      Write-WatchdogBreadcrumb ("startup sentinel active stage={0} age_s={1:N1}; skipping restart" -f ([string]$raw.stage), $ageSeconds)
      return $true
    }
    Remove-Item -Path $controllerStartupStatePath -Force -ErrorAction SilentlyContinue
    Write-WatchdogBreadcrumb ("startup sentinel stale age_s={0:N1}; removed" -f $ageSeconds)
  } catch {
    Write-WatchdogBreadcrumb ("startup sentinel unreadable; removing ({0})" -f $_.Exception.Message)
    Remove-Item -Path $controllerStartupStatePath -Force -ErrorAction SilentlyContinue
  }
  return $false
}

$scriptRoot = Split-Path -Parent $PSCommandPath
$root = (Resolve-Path (Join-Path $scriptRoot "..\..")).Path
$runtimeDir = Get-CodrexRuntimeDir -RepoRoot $root
$stateDir = Join-Path $runtimeDir "state"
$startScript = Join-Path $scriptRoot "start-controller.ps1"
$configPath = Join-Path $root "controller.config.json"
$logsDir = Join-Path $runtimeDir "logs"
$logPath = Join-Path $logsDir "watchdog.log"
$startupLogPath = Join-Path $logsDir "startup-bootstrap.log"
$controllerStartupStatePath = Join-Path $stateDir "controller.starting.json"

if (-not (Test-Path $startScript)) {
  throw "Missing start script at $startScript"
}
if (-not (Test-Path $logsDir)) {
  New-Item -Path $logsDir -ItemType Directory -Force | Out-Null
}
Write-WatchdogBreadcrumb ("invoked on port {0}" -f $Port)

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
  Write-WatchdogBreadcrumb ("health check ok on port {0}" -f $Port)
  exit 0
}

if (Test-RecentControllerStartup) {
  exit 0
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $logPath -Value "$stamp unhealthy on port $Port, restarting"
Write-WatchdogBreadcrumb ("health check failed on port {0}; launching restart" -f $Port)

try {
  $proc = Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile",
    "-WindowStyle", "Hidden",
    "-ExecutionPolicy", "Bypass",
    "-File", $startScript,
    "-Port", $Port
  ) -WindowStyle Hidden -PassThru
  if ($proc) {
    $proc.WaitForExit()
  }
  $done = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  Add-Content -Path $logPath -Value "$done restart command completed"
  Write-WatchdogBreadcrumb ("restart command completed on port {0}" -f $Port)
} catch {
  $fail = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  Add-Content -Path $logPath -Value "$fail restart failed: $($_.Exception.Message)"
  Write-WatchdogBreadcrumb ("restart failed on port {0}: {1}" -f $Port, $_.Exception.Message)
  throw
}
