param(
  [int]$Port = 48787,
  [int]$ProcId = 0
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $PSCommandPath
$root = (Resolve-Path (Join-Path $scriptRoot "..\..")).Path
$configPath = Join-Path $root "controller.config.json"

if ((-not $PSBoundParameters.ContainsKey("Port")) -and (Test-Path $configPath)) {
  try {
    $loaded = Get-Content $configPath -Raw | ConvertFrom-Json
    if ($loaded -and $loaded.port) {
      $Port = [int]$loaded.port
    }
  } catch {}
}

function Get-CodrexControllerProcesses {
  param(
    [int]$PortNumber
  )
  $pattern = "--port\s+$PortNumber\b"
  return Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -and $_.CommandLine -match "app\.server:app" -and $_.CommandLine -match $pattern }
}

function Stop-CodrexProcess {
  param(
    [object]$ProcessObject
  )
  if (-not $ProcessObject) {
    return $false
  }
  try {
    Stop-Process -Id $ProcessObject.ProcessId -Force -ErrorAction Stop
    Write-Host "Stopped PID $($ProcessObject.ProcessId)."
    return $true
  } catch {
    $msg = [string]$_.Exception.Message
    if ($msg -like "*Cannot find a process with the process identifier*") {
      Write-Host "PID $($ProcessObject.ProcessId) already exited."
      return $true
    }
    Write-Host "Failed to stop PID $($ProcessObject.ProcessId): $msg"
  }
  return $false
}

$stoppedAny = $false
if ($ProcId -gt 0) {
  $procById = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $ProcId) -ErrorAction SilentlyContinue
  if ($procById -and $procById.CommandLine -and $procById.CommandLine -match "app\.server:app") {
    $stoppedAny = (Stop-CodrexProcess -ProcessObject $procById) -or $stoppedAny
  }
}

$procs = Get-CodrexControllerProcesses -PortNumber $Port

if (-not $procs) {
  if (-not $stoppedAny) {
    Write-Host "No controller process found on port $Port."
  }
  exit 0
}

foreach ($p in $procs) {
  $stoppedAny = (Stop-CodrexProcess -ProcessObject $p) -or $stoppedAny
}
