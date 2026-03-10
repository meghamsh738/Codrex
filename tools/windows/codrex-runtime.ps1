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
  try {
    $route = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction Stop |
      Where-Object { $_.NextHop -and $_.NextHop -ne "0.0.0.0" } |
      Sort-Object RouteMetric, ifMetric |
      Select-Object -First 1
    if ($route) {
      $ip = Get-NetIPAddress -InterfaceIndex $route.ifIndex -AddressFamily IPv4 -ErrorAction Stop |
        Where-Object { $_.IPAddress -notlike "169.254*" -and $_.IPAddress -ne "127.0.0.1" } |
        Select-Object -First 1 -ExpandProperty IPAddress
      if ($ip) { return [string]$ip }
    }
  } catch {}
  try {
    $line = (ipconfig | Select-String "IPv4 Address").Line | Select-Object -First 1
    if ($line -match ":\s*([0-9\.]+)\s*$") { return [string]$matches[1] }
  } catch {}
  return "127.0.0.1"
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
  try {
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  } catch {
    return @()
  }
  if (-not $listeners) {
    return @()
  }
  $owners = New-Object System.Collections.Generic.List[object]
  foreach ($entry in ($listeners | Select-Object -Unique OwningProcess)) {
    $proc = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $entry.OwningProcess) -ErrorAction SilentlyContinue
    if ($proc -and $proc.CommandLine -and $proc.CommandLine -match "app\.server:app") {
      $owners.Add($proc) | Out-Null
    }
  }
  return @($owners | ForEach-Object { $_ })
}

function Test-PortListening {
  param(
    [int]$Port
  )
  try {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
  } catch {}
  return $false
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
  $lines = @(& powershell.exe @invokeArgs 2>&1 | ForEach-Object { [string]$_ })
  $exitCode = if ($LASTEXITCODE -is [int]) { [int]$LASTEXITCODE } else { 0 }
  return [pscustomobject]@{
    exit_code = $exitCode
    lines = @($lines)
    text = (($lines | Where-Object { $_ -ne $null }) -join "`n").Trim()
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
  $controllerOn = ($owners.Count -gt 0)
  $duplicateOwners = ($owners.Count -gt 1)
  $appRuntime = if ($controllerOn) { Get-AppRuntime -Port $port } else { $null }
  $appHealth = if ($appRuntime) { $appRuntime } elseif ($controllerOn) { Get-AppHealth -Port $port } else { $null }
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
    controller_pid = if ($owners.Count -gt 0) { [int]$owners[0].ProcessId } else { $null }
    controller_pids = @($owners | ForEach-Object { [int]$_.ProcessId })
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

function Repair-Runtime {
  param(
    [object]$Paths
  )
  $snapshot = Get-StatusSnapshot -Paths $Paths
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
  return [pscustomobject]@{
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
  }
}

function Start-Runtime {
  param(
    [object]$Paths,
    [int]$LaunchUiPort,
    [switch]$EnableFirewall
  )
  $snapshot = Get-StatusSnapshot -Paths $Paths
  if ($snapshot.status -eq "running") {
    return [pscustomobject]@{
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
    }
  }
  if ($snapshot.controller_pid -and $snapshot.app_ready -and -not $snapshot.duplicate_controllers) {
    $cfg = Get-EffectiveConfig -Paths $Paths
    $session = Write-MobileSession -Paths $Paths -Config $cfg -ControllerPort $snapshot.controller_port -UiMode "built"
    $fresh = Get-StatusSnapshot -Paths $Paths
    return [pscustomobject]@{
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
    }
  }
  if ($snapshot.status -ne "stopped") {
    $null = Repair-Runtime -Paths $Paths
  }
  $args = @("-UiPort", [string]$LaunchUiPort)
  if ($EnableFirewall) {
    $args += "-OpenFirewall"
  }
  $result = Invoke-ScriptCapture -ScriptPath $Paths.start_mobile_script -Arguments $args
  $fresh = Get-StatusSnapshot -Paths $Paths
  $detail = $fresh.detail
  if ($result.text) {
    $detail = if ($detail) { "$detail Output: $($result.text)" } else { $result.text }
  }
  if ($result.exit_code -ne 0 -or $fresh.status -ne "running") {
    return [pscustomobject]@{
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
    }
  }
  return [pscustomobject]@{
    ok = $true
    action = "start"
    status = $fresh.status
    detail = "Codrex app stack started."
    controller_port = $fresh.controller_port
    controller_pid = $fresh.controller_pid
    local_url = $fresh.local_url
    network_url = $fresh.network_url
    session_present = $fresh.session_present
    app_ready = $fresh.app_ready
    app_version = $fresh.app_version
    repo_rev = $fresh.repo_rev
    logs_dir = $fresh.logs_dir
    started = $true
    reused = $false
    exit_code = $result.exit_code
  }
}

function Stop-Runtime {
  param(
    [object]$Paths,
    [int]$LaunchUiPort
  )
  $snapshot = Get-StatusSnapshot -Paths $Paths
  $controllerPort = $snapshot.controller_port
  $result = Invoke-ScriptCapture -ScriptPath $Paths.stop_mobile_script -Arguments @("-UiPort", [string]$LaunchUiPort)
  $jsonLine = Find-JsonLine -Lines $result.lines
  $stopPayload = $null
  if ($jsonLine) {
    try {
      $stopPayload = $jsonLine | ConvertFrom-Json
    } catch {}
  }
  $fresh = Get-StatusSnapshot -Paths $Paths
  $ok = ($result.exit_code -eq 0) -and ($fresh.status -eq "stopped")
  return [pscustomobject]@{
    ok = $ok
    action = "stop"
    status = $fresh.status
    detail = if ($ok) { "Codrex app stack stopped." } elseif ($result.text) { $result.text } else { $fresh.detail }
    controller_port = $controllerPort
    controller_pid = $fresh.controller_pid
    local_url = $fresh.local_url
    network_url = $fresh.network_url
    session_present = $fresh.session_present
    app_ready = $fresh.app_ready
    repo_rev = $fresh.repo_rev
    logs_dir = $fresh.logs_dir
    controller_stopped = if ($stopPayload) { [string]$stopPayload.controller_status } else { "" }
    ui_stopped = if ($stopPayload) { [bool]$stopPayload.ui_stopped } else { $true }
    stale_session_removed = if ($stopPayload) { [bool]$stopPayload.stale_session_file_removed } else { (-not (Test-Path $Paths.session_path)) }
    exit_code = $result.exit_code
  }
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
