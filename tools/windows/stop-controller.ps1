param(
  [int]$Port = 48787,
  [int]$ProcId = 0
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $PSCommandPath
$root = (Resolve-Path (Join-Path $scriptRoot "..\..")).Path
$diagnosticsScript = Join-Path $scriptRoot "codrex-diagnostics.ps1"
if (Test-Path $diagnosticsScript) {
  . $diagnosticsScript
}
$configPath = Join-Path $root "controller.config.json"
$runtimeDir = if ($env:CODEX_RUNTIME_DIR -and $env:CODEX_RUNTIME_DIR.Trim()) {
  $env:CODEX_RUNTIME_DIR.Trim()
} elseif ($env:LocalAppData -and $env:LocalAppData.Trim()) {
  Join-Path $env:LocalAppData "Codrex\remote-ui"
} else {
  Join-Path $root ".runtime"
}
$localConfigPath = Join-Path (Join-Path $runtimeDir "state") "controller.config.local.json"
$legacyLocalConfigPath = Join-Path $root "controller.config.local.json"
$logsDir = Join-Path $runtimeDir "logs"
$script:DiagnosticsLayout = Ensure-CodrexDiagnosticsLayout -RuntimeDir $runtimeDir
$script:DiagActionId = Get-CodrexCurrentActionId
if (-not $script:DiagActionId) {
  $script:DiagActionId = New-CodrexActionId
}
$script:DiagActionName = Get-CodrexCurrentActionName
if (-not $script:DiagActionName) {
  $script:DiagActionName = "stop"
}
$script:DiagSource = "stop-controller"
$script:StoppedProcessIds = @()

function Write-StopControllerDiagnostic {
  param(
    [bool]$Ok,
    [string]$Detail,
    [AllowNull()]
    [object]$Extra = $null
  )
  $payload = [ordered]@{
    ok = $Ok
    status = if ($Ok) { "completed" } else { "error" }
    detail = $Detail
    repo_root = $root
    runtime_dir = $runtimeDir
    logs_dir = $logsDir
    controller_port = [int]$Port
    selected_pair_route = Get-CodrexSelectedRouteFromState -RuntimeDir $runtimeDir
    session_file = Join-Path (Join-Path $runtimeDir "state") "mobile.session.json"
    controller_port_snapshot_before = @($script:DiagBeforeControllerSnapshot)
    controller_port_snapshot_after = Get-CodrexPortDiagnosticsSnapshot -Ports @([int]$Port)
    linked_process_logs = [ordered]@{
      controller_stdout = Join-Path $logsDir "controller.out.log"
      controller_stderr = Join-Path $logsDir "controller.err.log"
    }
    stopped_process_ids = @($script:StoppedProcessIds)
  }
  if ($null -ne $Extra) {
    foreach ($property in $Extra.PSObject.Properties) {
      $payload[$property.Name] = $property.Value
    }
  }
  $null = Write-CodrexActionLog -RuntimeDir $runtimeDir -Action $script:DiagActionName -Source $script:DiagSource -Payload $payload -ActionId $script:DiagActionId -IsError:(-not $Ok)
  $null = Write-CodrexEventLog -RuntimeDir $runtimeDir -Source $script:DiagSource -Action $script:DiagActionName -ActionId $script:DiagActionId -Level $(if ($Ok) { "info" } else { "error" }) -Message $Detail -Context @{
    controller_port = [int]$Port
    stopped_process_ids = @($script:StoppedProcessIds)
  }
}

trap {
  $message = if ($_.Exception -and $_.Exception.Message) { [string]$_.Exception.Message } else { [string]$_ }
  Write-StopControllerDiagnostic -Ok:$false -Detail $message -Extra ([pscustomobject]@{
    failure_stage = "stop-controller"
  })
  exit 1
}

if (-not $PSBoundParameters.ContainsKey("Port")) {
  foreach ($candidate in @($localConfigPath, $legacyLocalConfigPath, $configPath)) {
    if (-not (Test-Path $candidate)) { continue }
    try {
      $loaded = Get-Content $candidate -Raw | ConvertFrom-Json
      if ($loaded -and $loaded.port) {
        $Port = [int]$loaded.port
        break
      }
    } catch {}
  }
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
    $script:StoppedProcessIds += @([int]$ProcessObject.ProcessId)
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

$script:DiagBeforeControllerSnapshot = Get-CodrexPortDiagnosticsSnapshot -Ports @([int]$Port)
$null = Write-CodrexEventLog -RuntimeDir $runtimeDir -Source $script:DiagSource -Action $script:DiagActionName -ActionId $script:DiagActionId -Message "Stopping controller script." -Context @{
  controller_port = [int]$Port
  controller_pid = [int]$ProcId
}

$procs = Get-CodrexControllerProcesses -PortNumber $Port

if (-not $procs) {
  if (-not $stoppedAny) {
    Write-Host "No controller process found on port $Port."
  }
  Write-StopControllerDiagnostic -Ok:$true -Detail ("No controller process found on port {0}." -f $Port) -Extra ([pscustomobject]@{
    stopped_any = $false
  })
  exit 0
}

foreach ($p in $procs) {
  $stoppedAny = (Stop-CodrexProcess -ProcessObject $p) -or $stoppedAny
}
Write-StopControllerDiagnostic -Ok:$true -Detail ("Controller stop completed for port {0}." -f $Port) -Extra ([pscustomobject]@{
  stopped_any = [bool]$stoppedAny
})
exit 0
