param(
  [ValidateSet("status", "start", "stop", "repair")]
  [string]$Action = "status",
  [int]$UiPort = 54312,
  [string]$RuntimeDir = "",
  [switch]$OpenFirewall
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $PSCommandPath
$root = (Resolve-Path (Join-Path $scriptRoot "..\..")).Path
$diagnosticsScript = Join-Path $scriptRoot "codrex-diagnostics.ps1"
if (Test-Path $diagnosticsScript) {
  . $diagnosticsScript
}
$script:RuntimeDirOverride = [string]$RuntimeDir
$script:DefaultControllerPort = 48787
$script:DefaultDevUiPort = 54312
$script:LegacyControllerPort = 8787

function Get-CodrexRuntimeDir {
  param(
    [string]$RepoRoot
  )
  if ($script:RuntimeDirOverride -and $script:RuntimeDirOverride.Trim()) {
    return $script:RuntimeDirOverride.Trim()
  }
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

function Read-JsonFile {
  param(
    [string]$Path
  )
  if (-not $Path -or -not (Test-Path $Path)) {
    return $null
  }
  try {
    return Get-Content -Path $Path -Raw | ConvertFrom-Json
  } catch {}
  return $null
}

function Write-JsonFile {
  param(
    [string]$Path,
    [object]$Data
  )
  $parent = Split-Path -Parent $Path
  if ($parent -and -not (Test-Path $parent)) {
    New-Item -Path $parent -ItemType Directory -Force | Out-Null
  }
  $Data | ConvertTo-Json -Depth 8 | Set-Content -Path $Path -Encoding UTF8
}

function Get-PrimaryIPv4 {
  return (Get-CodrexPrimaryIPv4)
}

function Get-RepoRevision {
  try {
    $rev = git -C $root rev-parse --short HEAD 2>$null | Select-Object -First 1
    if ($rev) {
      return ([string]$rev).Trim()
    }
  } catch {}
  return ""
}

function Get-Paths {
  $runtimeDir = Get-CodrexRuntimeDir -RepoRoot $root
  $stateDir = Join-Path $runtimeDir "state"
  $logsDir = Join-Path $runtimeDir "logs"
  $overrideActive = [string]$env:CODEX_RUNTIME_DIR
  $useLegacyFallbacks = -not ($overrideActive -and $overrideActive.Trim())
  return [pscustomobject]@{
    runtime_dir = $runtimeDir
    state_dir = $stateDir
    logs_dir = $logsDir
    config_path = Join-Path $root "controller.config.json"
    local_config_path = Join-Path $stateDir "controller.config.local.json"
    legacy_local_config_path = if ($useLegacyFallbacks) { Join-Path $root "controller.config.local.json" } else { "" }
    session_path = Join-Path $stateDir "mobile.session.json"
    legacy_session_path = if ($useLegacyFallbacks) { Join-Path (Join-Path $root "logs") "mobile.session.json" } else { "" }
    start_mobile_script = Join-Path $scriptRoot "start-mobile.ps1"
    stop_mobile_script = Join-Path $scriptRoot "stop-mobile.ps1"
  }
}

function Merge-Config {
  param(
    [object]$Defaults,
    [object]$Local
  )
  $cfg = [ordered]@{
    port = $script:DefaultControllerPort
    distro = "Ubuntu"
    workdir = "/home/megha/codrex-work"
    fileRoot = "/home/megha/codrex-work"
    token = ""
    telegramDefaultSend = $true
  }
  foreach ($source in @($Defaults, $Local)) {
    if (-not $source) { continue }
    try { if ($source.port) { $cfg.port = [int]$source.port } } catch {}
    try { if ($source.distro) { $cfg.distro = [string]$source.distro } } catch {}
    try { if ($source.workdir) { $cfg.workdir = [string]$source.workdir } } catch {}
    try { if ($source.fileRoot) { $cfg.fileRoot = [string]$source.fileRoot } } catch {}
    try { if ($source.token) { $cfg.token = [string]$source.token } } catch {}
    try {
      if ($null -ne $source.telegramDefaultSend) {
        $cfg.telegramDefaultSend = [bool]$source.telegramDefaultSend
      }
    } catch {}
  }
  if (-not $cfg.fileRoot) { $cfg.fileRoot = $cfg.workdir }
  if ([int]$cfg.port -eq $script:LegacyControllerPort) {
    $cfg.port = $script:DefaultControllerPort
  }
  return [pscustomobject]$cfg
}

function Get-EffectiveConfig {
  param(
    [object]$Paths
  )
  $defaults = Read-JsonFile -Path $Paths.config_path
  $local = Read-JsonFile -Path $Paths.local_config_path
  if (-not $local) {
    $local = Read-JsonFile -Path $Paths.legacy_local_config_path
  }
  return Merge-Config -Defaults $defaults -Local $local
}

function Save-LocalConfig {
  param(
    [object]$Paths,
    [object]$Config
  )
  $payload = [ordered]@{
    port = [int]$Config.port
    distro = [string]$Config.distro
    workdir = [string]$Config.workdir
    fileRoot = [string]$Config.fileRoot
    token = [string]$Config.token
    telegramDefaultSend = [bool]$Config.telegramDefaultSend
  }
  Write-JsonFile -Path $Paths.local_config_path -Data $payload
}

function Read-MobileSession {
  param(
    [object]$Paths
  )
  $session = Read-JsonFile -Path $Paths.session_path
  if ($session) {
    return $session
  }
  return Read-JsonFile -Path $Paths.legacy_session_path
}

function Remove-MobileSessionFiles {
  param(
    [object]$Paths
  )
  foreach ($path in @($Paths.session_path, $Paths.legacy_session_path)) {
    if ($path -and (Test-Path $path)) {
      Remove-Item -Path $path -Force -ErrorAction SilentlyContinue
    }
  }
}

function Get-CodrexControllerProcessesByPort {
  param(
    [int]$Port
  )
  if ($Port -le 0) {
    return @()
  }
  return @(
    Get-CodrexPortOwnerProcesses -Ports @($Port) |
      Where-Object { $_.CommandLine -and $_.CommandLine -match "app\.server:app" }
  )
}

function Get-CodrexControllerProcessById {
  param(
    [int]$ProcessId
  )
  if ($ProcessId -le 0) {
    return $null
  }
  try {
    $proc = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $ProcessId) -ErrorAction SilentlyContinue
    if ($proc -and $proc.CommandLine -and $proc.CommandLine -match "app\.server:app") {
      return $proc
    }
  } catch {}
  return $null
}

function Test-PortListening {
  param(
    [int]$Port
  )
  return (Test-CodrexPortListening -Port $Port)
}

function Stop-CodrexControllerProcesses {
  param(
    [int]$Port,
    [switch]$KeepNewest
  )
  $owners = @(Get-CodrexControllerProcessesByPort -Port $Port | Sort-Object ProcessId -Descending)
  $stopped = New-Object System.Collections.Generic.List[int]
  if (-not $owners -or $owners.Count -eq 0) {
    return [pscustomobject]@{
      stopped = @()
      kept = $null
    }
  }
  $keepProcess = $null
  if ($KeepNewest) {
    $keepProcess = $owners[0]
    $owners = @($owners | Select-Object -Skip 1)
  }
  foreach ($proc in $owners) {
    try {
      Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
      $stopped.Add([int]$proc.ProcessId) | Out-Null
    } catch {}
  }
  return [pscustomobject]@{
    stopped = @($stopped)
    kept = $keepProcess
  }
}

function Get-AppRuntime {
  param(
    [int]$Port
  )
  if ($Port -le 0) {
    return $null
  }
  try {
    return Invoke-RestMethod -UseBasicParsing -Uri ("http://127.0.0.1:{0}/app/runtime" -f $Port) -TimeoutSec 2
  } catch {}
  return $null
}

function Get-AppHealth {
  param(
    [int]$Port
  )
  if ($Port -le 0) {
    return $null
  }
  try {
    return Invoke-RestMethod -UseBasicParsing -Uri ("http://127.0.0.1:{0}/app/health" -f $Port) -TimeoutSec 2
  } catch {}
  return $null
}

function Get-ControllerPortFromState {
  param(
    [object]$Paths,
    [object]$Config,
    [object]$Session
  )
  if ($Session -and $Session.controller_port) {
    return [int]$Session.controller_port
  }
  if ($Config -and $Config.port) {
    return [int]$Config.port
  }
  return $script:DefaultControllerPort
}

function Write-MobileSession {
  param(
    [object]$Paths,
    [object]$Config,
    [int]$ControllerPort,
    [int]$UiPortValue = 0,
    [string]$UiMode = "built"
  )
  $owners = @(Get-CodrexControllerProcessesByPort -Port $ControllerPort | Sort-Object ProcessId -Descending)
  $controllerPid = if ($owners.Count -gt 0) { [int]$owners[0].ProcessId } else { $null }
  $lanIp = Get-PrimaryIPv4
  $payload = [ordered]@{
    started_at = (Get-Date).ToString("o")
    controller_port = [int]$ControllerPort
    controller_pid = $controllerPid
    ui_port = if ($UiPortValue -gt 0) { [int]$UiPortValue } else { $null }
    ui_pid = $null
    ui_mode = [string]$UiMode
    repo_root = $root
    runtime_dir = $Paths.runtime_dir
    session_file = $Paths.session_path
    app_url = ("http://127.0.0.1:{0}/" -f $ControllerPort)
    network_app_url = if ($lanIp -and $lanIp -ne "127.0.0.1") { ("http://{0}:{1}/" -f $lanIp, $ControllerPort) } else { "" }
  }
  Write-JsonFile -Path $Paths.session_path -Data $payload
  return Read-JsonFile -Path $Paths.session_path
}

function Get-StatusSummaryRecord {
  param(
    [object]$Snapshot
  )
  if (-not $Snapshot) {
    return $null
  }
  return [ordered]@{
    status = [string]$Snapshot.status
    detail = [string]$Snapshot.detail
    controller_port = [int]$Snapshot.controller_port
    controller_pid = $Snapshot.controller_pid
    controller_pids = @($Snapshot.controller_pids)
    session_present = [bool]$Snapshot.session_present
    session_file = [string]$Snapshot.session_file
    app_ready = [bool]$Snapshot.app_ready
    app_version = [string]$Snapshot.app_version
    ui_mode = [string]$Snapshot.ui_mode
    local_url = [string]$Snapshot.local_url
    network_url = [string]$Snapshot.network_url
  }
}

function Get-LinkedProcessLogs {
  param(
    [object]$Paths
  )
  return [ordered]@{
    controller_stdout = Join-Path $Paths.logs_dir "controller.out.log"
    controller_stderr = Join-Path $Paths.logs_dir "controller.err.log"
    ui_stdout = Join-Path $Paths.logs_dir "ui.out.log"
    ui_stderr = Join-Path $Paths.logs_dir "ui.err.log"
  }
}

function Finalize-ActionResult {
  param(
    [object]$Paths,
    [string]$ActionName,
    [object]$ResultPayload,
    [AllowNull()]
    [object]$ActionPayload = $null
  )
  $actionId = if ($ResultPayload.action_id) { [string]$ResultPayload.action_id } else { New-CodrexActionId }
  $payload = if ($ActionPayload) { $ActionPayload } else { $ResultPayload }
  $actionWrite = Write-CodrexActionLog -RuntimeDir $Paths.runtime_dir -Action $ActionName -Source "runtime" -Payload $payload -ActionId $actionId -IsError:(-not [bool]$ResultPayload.ok)
  $eventMessage = if ($ResultPayload.ok) {
    ("{0} completed with status '{1}'." -f $ActionName, $ResultPayload.status)
  } else {
    ("{0} failed with status '{1}'." -f $ActionName, $ResultPayload.status)
  }
  Write-CodrexEventLog -RuntimeDir $Paths.runtime_dir -Source "runtime" -Action $ActionName -ActionId $actionId -Level $(if ($ResultPayload.ok) { "info" } else { "error" }) -Message $eventMessage -Context @{
    detail = $ResultPayload.detail
    controller_port = $ResultPayload.controller_port
    controller_pid = $ResultPayload.controller_pid
    session_present = $ResultPayload.session_present
    app_ready = $ResultPayload.app_ready
    app_version = $ResultPayload.app_version
  } | Out-Null
  foreach ($pair in @(
    @{ Name = "action_id"; Value = $actionId },
    @{ Name = "diagnostic_log_path"; Value = $actionWrite.events_log },
    @{ Name = "last_action_path"; Value = $actionWrite.last_action_path },
    @{ Name = "last_error_path"; Value = $actionWrite.last_error_path }
  )) {
    try {
      if ($ResultPayload.PSObject.Properties[$pair.Name]) {
        $ResultPayload.PSObject.Properties[$pair.Name].Value = $pair.Value
      } else {
        $ResultPayload | Add-Member -NotePropertyName $pair.Name -NotePropertyValue $pair.Value -Force
      }
    } catch {}
  }
  return $ResultPayload
}

function Invoke-ScriptCapture {
  param(
    [string]$ScriptPath,
    [string[]]$Arguments = @()
  )
  if (-not (Test-Path $ScriptPath)) {
    throw "Missing script: $ScriptPath"
  }
  $invokeArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $ScriptPath
  )
  if ($Arguments) {
    $invokeArgs += $Arguments
  }
  $lines = New-Object System.Collections.Generic.List[string]
  $output = @(& powershell.exe @invokeArgs 2>&1)
  $exitCode = [int]$LASTEXITCODE
  foreach ($entry in $output) {
    if ($null -ne $entry) {
      $lines.Add([string]$entry) | Out-Null
    }
  }
  $allLines = @($lines)
  return [pscustomobject]@{
    exit_code = $exitCode
    lines = $allLines
    text = (($allLines | Where-Object { $_ -ne $null }) -join "`n").Trim()
  }
}

function Find-JsonLine {
  param(
    [string[]]$Lines
  )
  for ($index = $Lines.Count - 1; $index -ge 0; $index--) {
    $trimmed = [string]$Lines[$index]
    if (-not $trimmed) { continue }
    $trimmed = $trimmed.Trim()
    if ($trimmed.StartsWith("{") -and $trimmed.EndsWith("}")) {
      return $trimmed
    }
  }
  return ""
}

function Get-StatusSnapshot {
  param(
    [object]$Paths
  )
  $cfg = Get-EffectiveConfig -Paths $Paths
  $session = Read-MobileSession -Paths $Paths
  $port = Get-ControllerPortFromState -Paths $Paths -Config $cfg -Session $session
  $owners = @(Get-CodrexControllerProcessesByPort -Port $port | Sort-Object ProcessId -Descending)
  $sessionReportedPid = 0
  if ($session -and $session.controller_pid) {
    try {
      $sessionReportedPid = [int]$session.controller_pid
    } catch {}
  }
  $sessionProcess = if ($sessionReportedPid -gt 0) { Get-CodrexControllerProcessById -ProcessId $sessionReportedPid } else { $null }
  $sessionProcessAlive = [bool]$sessionProcess
  $controllerOn = ($owners.Count -gt 0) -or $sessionProcessAlive
  $duplicateOwners = ($owners.Count -gt 1)
  $portListening = if ($controllerOn) { Test-PortListening -Port $port } else { $false }
  $appRuntime = if ($portListening) { Get-AppRuntime -Port $port } else { $null }
  $appHealth = if ($appRuntime) { $appRuntime } elseif ($portListening) { Get-AppHealth -Port $port } else { $null }
  $appBuilt = [bool]($appHealth -and $appHealth.ok -and $appHealth.ui_mode -eq "built")
  $sessionPresent = [bool]$session
  $sessionValid = $false
  if ($sessionPresent -and $session.controller_port) {
    try {
      $sessionValid = ([int]$session.controller_port -eq $port)
    } catch {}
  }
  $status = "stopped"
  $detail = "No active controller."
  if ($controllerOn -and $appBuilt -and $sessionValid -and -not $duplicateOwners) {
    $status = "running"
    $detail = "Codrex app is ready."
  } elseif ($controllerOn -and $duplicateOwners) {
    $status = "recovering"
    $detail = "Duplicate Codrex controller processes detected."
  } elseif ($controllerOn -and $appBuilt -and -not $sessionValid) {
    $status = "recovering"
    $detail = "Controller is healthy but runtime session state is missing or stale."
  } elseif ($controllerOn -and $sessionValid) {
    $status = "checking"
    $detail = "Controller process is active and runtime session is present. Readiness is still settling."
  } elseif ($controllerOn) {
    $status = "checking"
    $detail = "Controller is running but app readiness is not confirmed yet."
  } elseif ($sessionPresent) {
    $status = "recovering"
    $detail = "Runtime session file exists without a live controller."
  }
  $localUrl = if ($controllerOn -or $sessionPresent) { "http://127.0.0.1:$port/" } else { "" }
  $lanIp = Get-PrimaryIPv4
  $networkUrl = if ($lanIp -and $lanIp -ne "127.0.0.1" -and ($controllerOn -or $sessionPresent)) { "http://$lanIp`:$port/" } else { "" }
  $repoRev = Get-RepoRevision
  return [pscustomobject]@{
    ok = $true
    action = "status"
    status = $status
    detail = $detail
    repo_root = $root
    repo_rev = $repoRev
    runtime_dir = $Paths.runtime_dir
    logs_dir = $Paths.logs_dir
    controller_port = $port
    controller_pid = if ($owners.Count -gt 0) { [int]$owners[0].ProcessId } elseif ($sessionProcessAlive) { [int]$sessionReportedPid } else { $null }
    controller_pids = if ($owners.Count -gt 0) { @($owners | ForEach-Object { [int]$_.ProcessId }) } elseif ($sessionProcessAlive) { @([int]$sessionReportedPid) } else { @() }
    duplicate_controllers = $duplicateOwners
    session_present = $sessionPresent
    session_file = $Paths.session_path
    session = if ($sessionPresent) { $session } else { $null }
    app_ready = $appBuilt
    app_version = if ($appRuntime -and $appRuntime.version) { [string]$appRuntime.version } else { "" }
    ui_mode = if ($appHealth -and $appHealth.ui_mode) { [string]$appHealth.ui_mode } else { "offline" }
    local_url = $localUrl
    network_url = $networkUrl
  }
}

function Wait-ForStableStartSnapshot {
  param(
    [object]$Paths,
    [int]$ExpectedPort,
    [int]$Attempts = 10,
    [int]$DelayMs = 120
  )
  $latest = Get-StatusSnapshot -Paths $Paths
  for ($attempt = 0; $attempt -lt $Attempts; $attempt++) {
    $controllerListening = Test-PortListening -Port $ExpectedPort
    $session = Read-MobileSession -Paths $Paths
    $sessionMatches = $false
    if ($session -and $session.controller_port) {
      try {
        $sessionMatches = ([int]$session.controller_port -eq $ExpectedPort)
      } catch {}
    }
    if ($latest.status -eq "running") {
      return $latest
    }
    if ($latest.status -eq "checking" -and $controllerListening -and $sessionMatches) {
      return $latest
    }
    if ($attempt -lt ($Attempts - 1)) {
      Start-Sleep -Milliseconds $DelayMs
      $latest = Get-StatusSnapshot -Paths $Paths
    }
  }
  return $latest
}

function Wait-ForMatchingSession {
  param(
    [object]$Paths,
    [int]$ExpectedPort,
    [int]$Attempts = 12,
    [int]$DelayMs = 100
  )
  $latest = Read-MobileSession -Paths $Paths
  for ($attempt = 0; $attempt -lt $Attempts; $attempt++) {
    if ($latest -and $latest.controller_port) {
      try {
        if ([int]$latest.controller_port -eq $ExpectedPort) {
          return $latest
        }
      } catch {}
    }
    if ($attempt -lt ($Attempts - 1)) {
      Start-Sleep -Milliseconds $DelayMs
      $latest = Read-MobileSession -Paths $Paths
    }
  }
  return $latest
}

function Test-ChildReportedReady {
  param(
    [object]$ScriptResult
  )
  if (-not $ScriptResult) {
    return $false
  }
  $text = [string]$ScriptResult.text
  if (-not $text) {
    return $false
  }
  return $text -match 'Mobile stack ready\.'
}

function Repair-Runtime {
  param(
    [object]$Paths
  )
  $actionId = New-CodrexActionId
  $snapshot = Get-StatusSnapshot -Paths $Paths
  $beforeSummary = Get-StatusSummaryRecord -Snapshot $snapshot
  $repaired = New-Object System.Collections.Generic.List[string]
  if ($snapshot.duplicate_controllers) {
    $result = Stop-CodrexControllerProcesses -Port $snapshot.controller_port -KeepNewest
    if ($result.stopped.Count -gt 0) {
      $repaired.Add(("stopped duplicate controllers: {0}" -f (($result.stopped | ForEach-Object { [string]$_ }) -join ","))) | Out-Null
    }
  }
  $snapshot = Get-StatusSnapshot -Paths $Paths
  if ($snapshot.session_present -and -not $snapshot.controller_pid) {
    Remove-MobileSessionFiles -Paths $Paths
    $repaired.Add("removed stale runtime session") | Out-Null
    $snapshot = Get-StatusSnapshot -Paths $Paths
  }
  if ($snapshot.controller_pid -and $snapshot.app_ready -and -not $snapshot.session_present) {
    $cfg = Get-EffectiveConfig -Paths $Paths
    $session = Write-MobileSession -Paths $Paths -Config $cfg -ControllerPort $snapshot.controller_port -UiMode "built"
    if ($session) {
      $repaired.Add("rewrote missing runtime session") | Out-Null
      $snapshot = Get-StatusSnapshot -Paths $Paths
    }
  }
  $resultPayload = [pscustomobject]@{
    ok = $true
    action = "repair"
    repaired = ($repaired.Count -gt 0)
    repair_steps = @($repaired)
    status = $snapshot.status
    detail = if ($repaired.Count -gt 0) { ($repaired -join "; ") } else { $snapshot.detail }
    controller_port = $snapshot.controller_port
    local_url = $snapshot.local_url
    network_url = $snapshot.network_url
    session_present = $snapshot.session_present
    app_ready = $snapshot.app_ready
    repo_rev = $snapshot.repo_rev
    logs_dir = $snapshot.logs_dir
    action_id = $actionId
  }
  $afterSummary = Get-StatusSummaryRecord -Snapshot $snapshot
  $actionPayload = [ordered]@{
    ok = $resultPayload.ok
    status = $resultPayload.status
    detail = $resultPayload.detail
    repaired = $resultPayload.repaired
    repair_steps = @($resultPayload.repair_steps)
    repo_root = $root
    repo_rev = $snapshot.repo_rev
    runtime_dir = $Paths.runtime_dir
    logs_dir = $Paths.logs_dir
    selected_pair_route = Get-CodrexSelectedRouteFromState -RuntimeDir $Paths.runtime_dir
    controller_port = $snapshot.controller_port
    local_url = $snapshot.local_url
    network_url = $snapshot.network_url
    session_file = $Paths.session_path
    session_state_before = if ($beforeSummary.session_present) { "present" } else { "missing" }
    session_state_after = if ($afterSummary.session_present) { "present" } else { "missing" }
    app_runtime_before = $beforeSummary
    app_runtime_after = $afterSummary
    controller_port_snapshot_before = Get-CodrexPortDiagnosticsSnapshot -Ports @($beforeSummary.controller_port)
    controller_port_snapshot_after = Get-CodrexPortDiagnosticsSnapshot -Ports @($afterSummary.controller_port)
    ui_port_snapshot_before = @()
    ui_port_snapshot_after = @()
    linked_process_logs = Get-LinkedProcessLogs -Paths $Paths
  }
  return Finalize-ActionResult -Paths $Paths -ActionName "repair" -ResultPayload $resultPayload -ActionPayload $actionPayload
}

function Start-Runtime {
  param(
    [object]$Paths,
    [int]$LaunchUiPort,
    [switch]$EnableFirewall
  )
  $actionId = New-CodrexActionId
  $snapshot = Get-StatusSnapshot -Paths $Paths
  $beforeSummary = Get-StatusSummaryRecord -Snapshot $snapshot
  $beforeControllerPort = [int]$snapshot.controller_port
  $beforeUiPort = if ($LaunchUiPort -gt 0) { [int]$LaunchUiPort } else { 0 }
  if ($snapshot.status -eq "running") {
    $resultPayload = [pscustomobject]@{
      ok = $true
      action = "start"
      status = "running"
      detail = "Codrex app is already running."
      controller_port = $snapshot.controller_port
      controller_pid = $snapshot.controller_pid
      local_url = $snapshot.local_url
      network_url = $snapshot.network_url
      session_present = $snapshot.session_present
      app_ready = $snapshot.app_ready
      app_version = $snapshot.app_version
      repo_rev = $snapshot.repo_rev
      logs_dir = $snapshot.logs_dir
      started = $false
      reused = $true
      action_id = $actionId
    }
    $actionPayload = [ordered]@{
      ok = $resultPayload.ok
      status = $resultPayload.status
      detail = $resultPayload.detail
      repo_root = $root
      repo_rev = $snapshot.repo_rev
      runtime_dir = $Paths.runtime_dir
      logs_dir = $Paths.logs_dir
      selected_pair_route = Get-CodrexSelectedRouteFromState -RuntimeDir $Paths.runtime_dir
      controller_port = $snapshot.controller_port
      ui_port = $beforeUiPort
      local_url = $snapshot.local_url
      network_url = $snapshot.network_url
      session_file = $Paths.session_path
      session_state_before = if ($beforeSummary.session_present) { "present" } else { "missing" }
      session_state_after = if ($beforeSummary.session_present) { "present" } else { "missing" }
      app_runtime_before = $beforeSummary
      app_runtime_after = $beforeSummary
      controller_port_snapshot_before = Get-CodrexPortDiagnosticsSnapshot -Ports @($beforeControllerPort)
      controller_port_snapshot_after = Get-CodrexPortDiagnosticsSnapshot -Ports @($beforeControllerPort)
      ui_port_snapshot_before = Get-CodrexPortDiagnosticsSnapshot -Ports @($beforeUiPort)
      ui_port_snapshot_after = Get-CodrexPortDiagnosticsSnapshot -Ports @($beforeUiPort)
      linked_process_logs = Get-LinkedProcessLogs -Paths $Paths
      child_invocation = $null
      started = $false
      reused = $true
    }
    return Finalize-ActionResult -Paths $Paths -ActionName "start" -ResultPayload $resultPayload -ActionPayload $actionPayload
  }
  if ($snapshot.controller_pid -and $snapshot.app_ready -and -not $snapshot.duplicate_controllers) {
    $cfg = Get-EffectiveConfig -Paths $Paths
    $session = Write-MobileSession -Paths $Paths -Config $cfg -ControllerPort $snapshot.controller_port -UiMode "built"
    $fresh = Get-StatusSnapshot -Paths $Paths
    $freshSummary = Get-StatusSummaryRecord -Snapshot $fresh
    $resultPayload = [pscustomobject]@{
      ok = $true
      action = "start"
      status = $fresh.status
      detail = "Recovered runtime session for the existing Codrex controller."
      controller_port = $fresh.controller_port
      controller_pid = $fresh.controller_pid
      local_url = $fresh.local_url
      network_url = $fresh.network_url
      session_present = $fresh.session_present
      app_ready = $fresh.app_ready
      app_version = $fresh.app_version
      repo_rev = $fresh.repo_rev
      logs_dir = $fresh.logs_dir
      started = $false
      reused = $true
      session = $session
      action_id = $actionId
    }
    $actionPayload = [ordered]@{
      ok = $resultPayload.ok
      status = $resultPayload.status
      detail = $resultPayload.detail
      repo_root = $root
      repo_rev = $fresh.repo_rev
      runtime_dir = $Paths.runtime_dir
      logs_dir = $Paths.logs_dir
      selected_pair_route = Get-CodrexSelectedRouteFromState -RuntimeDir $Paths.runtime_dir
      controller_port = $fresh.controller_port
      ui_port = $beforeUiPort
      local_url = $fresh.local_url
      network_url = $fresh.network_url
      session_file = $Paths.session_path
      session_state_before = if ($beforeSummary.session_present) { "present" } else { "missing" }
      session_state_after = if ($freshSummary.session_present) { "present" } else { "missing" }
      app_runtime_before = $beforeSummary
      app_runtime_after = $freshSummary
      controller_port_snapshot_before = Get-CodrexPortDiagnosticsSnapshot -Ports @($beforeControllerPort)
      controller_port_snapshot_after = Get-CodrexPortDiagnosticsSnapshot -Ports @($fresh.controller_port)
      ui_port_snapshot_before = Get-CodrexPortDiagnosticsSnapshot -Ports @($beforeUiPort)
      ui_port_snapshot_after = Get-CodrexPortDiagnosticsSnapshot -Ports @($beforeUiPort)
      linked_process_logs = Get-LinkedProcessLogs -Paths $Paths
      child_invocation = $null
      started = $false
      reused = $true
    }
    return Finalize-ActionResult -Paths $Paths -ActionName "start" -ResultPayload $resultPayload -ActionPayload $actionPayload
  }
  if ($snapshot.status -ne "stopped") {
    $null = Repair-Runtime -Paths $Paths
  }
  $args = @("-UiPort", [string]$LaunchUiPort)
  if ($EnableFirewall) {
    $args += "-OpenFirewall"
  }
  $previousRuntimeDir = [string]$env:CODEX_RUNTIME_DIR
  $previousActionId = [string]$env:CODEX_ACTION_ID
  $previousActionName = [string]$env:CODEX_ACTION_NAME
  $previousActionSource = [string]$env:CODEX_ACTION_SOURCE
  $env:CODEX_RUNTIME_DIR = [string]$Paths.runtime_dir
  $env:CODEX_ACTION_ID = $actionId
  $env:CODEX_ACTION_NAME = "start"
  $env:CODEX_ACTION_SOURCE = "runtime"
  Write-CodrexEventLog -RuntimeDir $Paths.runtime_dir -Source "runtime" -Action "start" -ActionId $actionId -Message "Starting Codrex runtime action." -Context @{
    controller_port = $beforeControllerPort
    ui_port = $beforeUiPort
    selected_pair_route = Get-CodrexSelectedRouteFromState -RuntimeDir $Paths.runtime_dir
    arguments = @($args)
  } | Out-Null
  try {
    $result = Invoke-ScriptCapture -ScriptPath $Paths.start_mobile_script -Arguments $args
  } finally {
    if ($previousRuntimeDir) {
      $env:CODEX_RUNTIME_DIR = $previousRuntimeDir
    } else {
      Remove-Item Env:CODEX_RUNTIME_DIR -ErrorAction SilentlyContinue
    }
    if ($previousActionId) {
      $env:CODEX_ACTION_ID = $previousActionId
    } else {
      Remove-Item Env:CODEX_ACTION_ID -ErrorAction SilentlyContinue
    }
    if ($previousActionName) {
      $env:CODEX_ACTION_NAME = $previousActionName
    } else {
      Remove-Item Env:CODEX_ACTION_NAME -ErrorAction SilentlyContinue
    }
    if ($previousActionSource) {
      $env:CODEX_ACTION_SOURCE = $previousActionSource
    } else {
      Remove-Item Env:CODEX_ACTION_SOURCE -ErrorAction SilentlyContinue
    }
  }
  $childReportedReady = Test-ChildReportedReady -ScriptResult $result
  $expectedPortAfterStart = $beforeControllerPort
  $sessionAfterStart = $null
  $fresh = $null
  if ($result.exit_code -eq 0) {
    $sessionAfterStart = Read-MobileSession -Paths $Paths
    if ($sessionAfterStart -and $sessionAfterStart.controller_port) {
      try {
        $expectedPortAfterStart = [int]$sessionAfterStart.controller_port
      } catch {}
    }
    $sessionAfterStart = Wait-ForMatchingSession -Paths $Paths -ExpectedPort $expectedPortAfterStart
    if ($sessionAfterStart -and $sessionAfterStart.controller_port) {
      try {
        $expectedPortAfterStart = [int]$sessionAfterStart.controller_port
      } catch {}
    }
    $fresh = Wait-ForStableStartSnapshot -Paths $Paths -ExpectedPort $expectedPortAfterStart
  } else {
    $sessionAfterStart = Read-MobileSession -Paths $Paths
    $fresh = Get-StatusSnapshot -Paths $Paths
  }
  $sessionMatchesPort = $false
  if ($sessionAfterStart -and $sessionAfterStart.controller_port) {
    try {
      $sessionMatchesPort = ([int]$sessionAfterStart.controller_port -eq $beforeControllerPort)
    } catch {}
  }
  $controllerListeningAfterStart = Test-PortListening -Port $expectedPortAfterStart
  $treatAsStarted = ($result.exit_code -eq 0) -and (
    $fresh.status -eq "running" -or
    ($fresh.status -eq "checking" -and $controllerListeningAfterStart -and $sessionMatchesPort) -or
    ($childReportedReady -and $sessionMatchesPort)
  )
  $afterSummary = Get-StatusSummaryRecord -Snapshot $fresh
  $detail = $fresh.detail
  if ($result.text) {
    $detail = if ($detail) { "$detail Output: $($result.text)" } else { $result.text }
  }
  $resultPayload = $null
  if (-not $treatAsStarted) {
    $resultPayload = [pscustomobject]@{
      ok = $false
      action = "start"
      status = if ($fresh.status) { $fresh.status } else { "error" }
      detail = if ($detail) { $detail } else { "Codrex did not reach running state." }
      controller_port = $fresh.controller_port
      controller_pid = $fresh.controller_pid
      local_url = $fresh.local_url
      network_url = $fresh.network_url
      session_present = $fresh.session_present
      app_ready = $fresh.app_ready
      app_version = $fresh.app_version
      repo_rev = $fresh.repo_rev
      logs_dir = $fresh.logs_dir
      started = $false
      reused = $false
      exit_code = $result.exit_code
      action_id = $actionId
    }
  } else {
    $resultPayload = [pscustomobject]@{
      ok = $true
      action = "start"
      status = if ($fresh.status) { $fresh.status } else { "checking" }
      detail = if ($childReportedReady -and $fresh.status -ne "running") {
        "Codrex app stack started and is finalizing readiness."
      } else {
        "Codrex app stack started."
      }
      controller_port = if ($fresh.controller_port) { $fresh.controller_port } else { $beforeControllerPort }
      controller_pid = $fresh.controller_pid
      local_url = if ($fresh.local_url) { $fresh.local_url } else { "http://127.0.0.1:$beforeControllerPort/" }
      network_url = $fresh.network_url
      session_present = if ($sessionAfterStart) { $true } else { $fresh.session_present }
      app_ready = $fresh.app_ready
      app_version = $fresh.app_version
      repo_rev = $fresh.repo_rev
      logs_dir = $fresh.logs_dir
      started = $true
      reused = $false
      exit_code = $result.exit_code
      action_id = $actionId
    }
  }
  $actionPayload = [ordered]@{
    ok = $resultPayload.ok
    status = $resultPayload.status
    detail = $resultPayload.detail
    repo_root = $root
    repo_rev = $fresh.repo_rev
    runtime_dir = $Paths.runtime_dir
    logs_dir = $Paths.logs_dir
    selected_pair_route = Get-CodrexSelectedRouteFromState -RuntimeDir $Paths.runtime_dir
    controller_port = $fresh.controller_port
    ui_port = $beforeUiPort
    local_url = $fresh.local_url
    network_url = $fresh.network_url
    session_file = $Paths.session_path
    session_state_before = if ($beforeSummary.session_present) { "present" } else { "missing" }
    session_state_after = if ($afterSummary.session_present) { "present" } else { "missing" }
    app_runtime_before = $beforeSummary
    app_runtime_after = $afterSummary
    controller_port_snapshot_before = Get-CodrexPortDiagnosticsSnapshot -Ports @($beforeControllerPort)
    controller_port_snapshot_after = Get-CodrexPortDiagnosticsSnapshot -Ports @($fresh.controller_port)
    ui_port_snapshot_before = Get-CodrexPortDiagnosticsSnapshot -Ports @($beforeUiPort)
    ui_port_snapshot_after = Get-CodrexPortDiagnosticsSnapshot -Ports @($beforeUiPort)
    child_invocation = [ordered]@{
      script_path = $Paths.start_mobile_script
      arguments = @($args)
      exit_code = $result.exit_code
      output_tail = Get-CodrexTextTail -Text $result.lines
    }
    linked_process_logs = Get-LinkedProcessLogs -Paths $Paths
    started = $resultPayload.started
    reused = $resultPayload.reused
  }
  return Finalize-ActionResult -Paths $Paths -ActionName "start" -ResultPayload $resultPayload -ActionPayload $actionPayload
}

function Stop-Runtime {
  param(
    [object]$Paths,
    [int]$LaunchUiPort
  )
  $actionId = New-CodrexActionId
  $snapshot = Get-StatusSnapshot -Paths $Paths
  $controllerPort = $snapshot.controller_port
  $beforeSummary = Get-StatusSummaryRecord -Snapshot $snapshot
  $beforeUiPort = if ($LaunchUiPort -gt 0) { [int]$LaunchUiPort } else { 0 }
  $previousRuntimeDir = [string]$env:CODEX_RUNTIME_DIR
  $previousActionId = [string]$env:CODEX_ACTION_ID
  $previousActionName = [string]$env:CODEX_ACTION_NAME
  $previousActionSource = [string]$env:CODEX_ACTION_SOURCE
  $env:CODEX_RUNTIME_DIR = [string]$Paths.runtime_dir
  $env:CODEX_ACTION_ID = $actionId
  $env:CODEX_ACTION_NAME = "stop"
  $env:CODEX_ACTION_SOURCE = "runtime"
  Write-CodrexEventLog -RuntimeDir $Paths.runtime_dir -Source "runtime" -Action "stop" -ActionId $actionId -Message "Stopping Codrex runtime action." -Context @{
    controller_port = $controllerPort
    ui_port = $beforeUiPort
    selected_pair_route = Get-CodrexSelectedRouteFromState -RuntimeDir $Paths.runtime_dir
  } | Out-Null
  try {
    $result = Invoke-ScriptCapture -ScriptPath $Paths.stop_mobile_script -Arguments @("-UiPort", [string]$LaunchUiPort)
  } finally {
    if ($previousRuntimeDir) {
      $env:CODEX_RUNTIME_DIR = $previousRuntimeDir
    } else {
      Remove-Item Env:CODEX_RUNTIME_DIR -ErrorAction SilentlyContinue
    }
    if ($previousActionId) {
      $env:CODEX_ACTION_ID = $previousActionId
    } else {
      Remove-Item Env:CODEX_ACTION_ID -ErrorAction SilentlyContinue
    }
    if ($previousActionName) {
      $env:CODEX_ACTION_NAME = $previousActionName
    } else {
      Remove-Item Env:CODEX_ACTION_NAME -ErrorAction SilentlyContinue
    }
    if ($previousActionSource) {
      $env:CODEX_ACTION_SOURCE = $previousActionSource
    } else {
      Remove-Item Env:CODEX_ACTION_SOURCE -ErrorAction SilentlyContinue
    }
  }
  $jsonLine = Find-JsonLine -Lines $result.lines
  $stopPayload = $null
  if ($jsonLine) {
    try {
      $stopPayload = $jsonLine | ConvertFrom-Json
    } catch {}
  }
  $controllerStillListening = Test-PortListening -Port $controllerPort
  $uiStillListening = if ($beforeUiPort -gt 0) { Test-PortListening -Port $beforeUiPort } else { $false }
  $sessionStillPresent = (Test-Path $Paths.session_path) -or ($Paths.legacy_session_path -and (Test-Path $Paths.legacy_session_path))
  $ok = ($result.exit_code -eq 0) -and (-not $controllerStillListening) -and (-not $uiStillListening) -and (-not $sessionStillPresent)
  $repoRev = Get-RepoRevision
  $afterSummary = [pscustomobject]@{
    status = if ($ok) { "stopped" } else { "recovering" }
    detail = if ($ok) { "Codrex app stack stopped." } else { "Codrex app stack stop did not complete cleanly." }
    controller_port = $controllerPort
    controller_pid = $null
    session_present = $sessionStillPresent
    app_ready = $false
    repo_rev = $repoRev
    logs_dir = $Paths.logs_dir
    local_url = ""
    network_url = ""
  }
  $resultPayload = [pscustomobject]@{
    ok = $ok
    action = "stop"
    status = $afterSummary.status
    detail = if ($ok) { "Codrex app stack stopped." } elseif ($result.text) { $result.text } else { $afterSummary.detail }
    controller_port = $controllerPort
    controller_pid = $null
    local_url = ""
    network_url = ""
    session_present = $sessionStillPresent
    app_ready = $false
    repo_rev = $repoRev
    logs_dir = $Paths.logs_dir
    controller_stopped = if ($stopPayload) { [string]$stopPayload.controller_status } else { "" }
    ui_stopped = if ($stopPayload) { [bool]$stopPayload.ui_stopped } else { $true }
    stale_session_removed = if ($stopPayload) { [bool]$stopPayload.stale_session_file_removed } else { (-not (Test-Path $Paths.session_path)) }
    exit_code = $result.exit_code
    action_id = $actionId
  }
  $actionPayload = [ordered]@{
    ok = $resultPayload.ok
    status = $resultPayload.status
    detail = $resultPayload.detail
    repo_root = $root
    repo_rev = $repoRev
    runtime_dir = $Paths.runtime_dir
    logs_dir = $Paths.logs_dir
    selected_pair_route = Get-CodrexSelectedRouteFromState -RuntimeDir $Paths.runtime_dir
    controller_port = $controllerPort
    ui_port = $beforeUiPort
    local_url = ""
    network_url = ""
    session_file = $Paths.session_path
    session_state_before = if ($beforeSummary.session_present) { "present" } else { "missing" }
    session_state_after = if ($afterSummary.session_present) { "present" } else { "missing" }
    app_runtime_before = $beforeSummary
    app_runtime_after = $afterSummary
    controller_port_snapshot_before = Get-CodrexPortDiagnosticsSnapshot -Ports @($controllerPort)
    controller_port_snapshot_after = Get-CodrexPortDiagnosticsSnapshot -Ports @($controllerPort)
    ui_port_snapshot_before = Get-CodrexPortDiagnosticsSnapshot -Ports @($beforeUiPort)
    ui_port_snapshot_after = Get-CodrexPortDiagnosticsSnapshot -Ports @($beforeUiPort)
    child_invocation = [ordered]@{
      script_path = $Paths.stop_mobile_script
      arguments = @("-UiPort", [string]$LaunchUiPort)
      exit_code = $result.exit_code
      output_tail = Get-CodrexTextTail -Text $result.lines
    }
    linked_process_logs = Get-LinkedProcessLogs -Paths $Paths
    controller_stopped = $resultPayload.controller_stopped
    ui_stopped = $resultPayload.ui_stopped
    stale_session_removed = $resultPayload.stale_session_removed
  }
  return Finalize-ActionResult -Paths $Paths -ActionName "stop" -ResultPayload $resultPayload -ActionPayload $actionPayload
}

$paths = Get-Paths
foreach ($dir in @($paths.runtime_dir, $paths.state_dir, $paths.logs_dir)) {
  if (-not (Test-Path $dir)) {
    New-Item -Path $dir -ItemType Directory -Force | Out-Null
  }
}

$result = switch ($Action) {
  "status" { Get-StatusSnapshot -Paths $paths }
  "repair" { Repair-Runtime -Paths $paths }
  "start" { Start-Runtime -Paths $paths -LaunchUiPort $UiPort -EnableFirewall:$OpenFirewall }
  "stop" { Stop-Runtime -Paths $paths -LaunchUiPort $UiPort }
}

$result | ConvertTo-Json -Depth 8 -Compress | Write-Output
if (-not $result.ok) {
  exit 1
}
