param(
  [int]$UiPort = 4312,
  [switch]$KeepController
)

$ErrorActionPreference = "Stop"

function Read-SessionData {
  param([string]$Path)
  if (-not (Test-Path $Path)) { return $null }
  try {
    return (Get-Content -Path $Path -Raw | ConvertFrom-Json)
  } catch {}
  return $null
}

function Stop-UiProcessById {
  param([int]$ProcId)
  $p = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $ProcId) -ErrorAction SilentlyContinue
  if (-not $p) { return $false }
  try {
    Stop-Process -Id $ProcId -Force -ErrorAction Stop
    Write-Host "Stopped UI PID $ProcId."
    return $true
  } catch {
    Write-Host ("Failed to stop UI PID {0}: {1}" -f $ProcId, $_.Exception.Message)
  }
  return $false
}

function Stop-UiByPort {
  param([int]$Port)
  $stoppedAny = $false
  try {
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  } catch {
    $listeners = @()
  }
  if (-not $listeners) { return $false }

  foreach ($item in ($listeners | Select-Object -Unique OwningProcess)) {
    $procId = [int]$item.OwningProcess
    $proc = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $procId) -ErrorAction SilentlyContinue
    if (-not $proc) { continue }

    $looksLikeUi = $false
    if ($proc.CommandLine -and $proc.CommandLine -match "vite") { $looksLikeUi = $true }
    if ($proc.Name -match "node|npm") { $looksLikeUi = $true }

    if ($looksLikeUi) {
      try {
        Stop-Process -Id $procId -Force -ErrorAction Stop
        Write-Host "Stopped UI listener PID $procId on port $Port."
        $stoppedAny = $true
      } catch {
        Write-Host ("Failed to stop PID {0} on port {1}: {2}" -f $procId, $Port, $_.Exception.Message)
      }
    } else {
      Write-Host "Port $Port is owned by PID $procId ($($proc.Name)); not stopping automatically."
    }
  }
  return $stoppedAny
}

function Read-ControllerPort {
  param([string]$ConfigPath)
  if (-not (Test-Path $ConfigPath)) { return 8787 }
  try {
    $cfg = Get-Content -Path $ConfigPath -Raw | ConvertFrom-Json
    if ($cfg -and $cfg.port) { return [int]$cfg.port }
  } catch {}
  return 8787
}

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

$root = Split-Path -Parent $PSCommandPath
$runtimeDir = Get-CodrexRuntimeDir -RepoRoot $root
$stateDir = Join-Path $runtimeDir "state"
$sessionPath = Join-Path $stateDir "mobile.session.json"
$legacySessionPath = Join-Path (Join-Path $root "logs") "mobile.session.json"
$configPath = Join-Path $root "controller.config.json"

$session = Read-SessionData -Path $sessionPath
if (-not $session -and (Test-Path $legacySessionPath)) {
  $session = Read-SessionData -Path $legacySessionPath
}
$controllerPort = Read-ControllerPort -ConfigPath $configPath

if ($session -and $session.controller_port) {
  $controllerPort = [int]$session.controller_port
}
if ($session -and $session.ui_port) {
  $UiPort = [int]$session.ui_port
}

$uiStoppedBySession = $false
if ($session -and $session.ui_pid) {
  $uiStoppedBySession = Stop-UiProcessById -ProcId ([int]$session.ui_pid)
}
$uiStoppedByPort = Stop-UiByPort -Port $UiPort
if (-not $uiStoppedBySession -and -not $uiStoppedByPort) {
  Write-Host "No mobile UI process stopped (port $UiPort)."
}

if (-not $KeepController) {
  $stopControllerScript = Join-Path $root "stop-controller.ps1"
  if (Test-Path $stopControllerScript) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopControllerScript -Port $controllerPort
  } else {
    Write-Host "Missing stop script at $stopControllerScript"
  }
}

if (Test-Path $sessionPath) {
  Remove-Item $sessionPath -Force -ErrorAction SilentlyContinue
}
if (Test-Path $legacySessionPath) {
  Remove-Item $legacySessionPath -Force -ErrorAction SilentlyContinue
}

Write-Host "Done."
