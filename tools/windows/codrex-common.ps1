Set-StrictMode -Version Latest

function Get-RepoRoot {
  return (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent)
}

function Get-ControllerPythonExe {
  $root = Get-RepoRoot
  $candidates = @(
    (Join-Path $root ".venv.recovered\Scripts\python.exe"),
    (Join-Path $root ".venv\Scripts\python.exe")
  )
  foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) {
      return $candidate
    }
  }
  return $null
}

function Get-RuntimeDir {
  if ($env:CODEX_RUNTIME_DIR -and $env:CODEX_RUNTIME_DIR.Trim()) {
    return $env:CODEX_RUNTIME_DIR
  }
  return (Join-Path $env:LOCALAPPDATA "Codrex\remote-ui")
}

function Get-LogsDir {
  return (Join-Path (Get-RuntimeDir) "logs")
}

function Get-StateDir {
  return (Join-Path (Get-RuntimeDir) "state")
}

function Get-ActionLogsDir {
  return (Join-Path (Get-LogsDir) "actions")
}

function Get-ControllerConfigPath {
  return (Join-Path (Get-StateDir) "controller.config.local.json")
}

function Get-LauncherStatePath {
  return (Join-Path (Get-StateDir) "launcher.state.json")
}

function Get-SessionFilePath {
  return (Join-Path (Get-StateDir) "mobile.session.json")
}

function Get-LastActionPath {
  return (Join-Path (Get-LogsDir) "last-action.json")
}

function Get-LastErrorPath {
  return (Join-Path (Get-LogsDir) "last-error.json")
}

function Get-LauncherEventsPath {
  return (Join-Path (Get-LogsDir) "launcher-events.log")
}

function Ensure-CodrexDirs {
  $paths = @(
    (Get-RuntimeDir),
    (Get-LogsDir),
    (Get-StateDir),
    (Get-ActionLogsDir)
  )
  foreach ($path in $paths) {
    if (-not (Test-Path -LiteralPath $path)) {
      New-Item -ItemType Directory -Path $path -Force | Out-Null
    }
  }
}

function Read-JsonFile {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  if (-not (Test-Path -LiteralPath $Path)) {
    return $null
  }
  $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
  if (-not $raw.Trim()) {
    return $null
  }
  return ($raw | ConvertFrom-Json)
}

function Write-JsonFile {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [Parameter(Mandatory = $true)]
    $Payload
  )

  $dir = Split-Path -Parent $Path
  if ($dir -and -not (Test-Path -LiteralPath $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
  }
  ($Payload | ConvertTo-Json -Depth 12) | Set-Content -LiteralPath $Path -Encoding UTF8
}

function New-CodrexToken {
  $bytes = New-Object byte[] 24
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  $rng.GetBytes($bytes)
  $raw = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
  return $raw
}

function Mask-Secret {
  param([string]$Secret)
  if (-not $Secret) { return "" }
  if ($Secret.Length -le 10) { return $Secret }
  return ("{0}...{1}" -f $Secret.Substring(0, 6), $Secret.Substring($Secret.Length - 4))
}

function Get-ControllerConfig {
  Ensure-CodrexDirs
  $path = Get-ControllerConfigPath
  $cfg = Read-JsonFile -Path $path
  if (-not $cfg) {
    $cfg = [ordered]@{
      port = 48787
      distro = "Ubuntu"
      workdir = "/home/megha/codrex-work"
      fileRoot = "/home/megha/codrex-work"
      token = New-CodrexToken
      telegramDefaultSend = $true
    }
    Write-JsonFile -Path $path -Payload $cfg
    return $cfg
  }

  $changed = $false
  if (-not $cfg.port) { $cfg.port = 48787; $changed = $true }
  if (-not $cfg.distro) { $cfg.distro = "Ubuntu"; $changed = $true }
  if (-not $cfg.workdir) { $cfg.workdir = "/home/megha/codrex-work"; $changed = $true }
  if (-not $cfg.fileRoot) { $cfg.fileRoot = $cfg.workdir; $changed = $true }
  if (-not $cfg.token) { $cfg.token = New-CodrexToken; $changed = $true }
  if ($null -eq $cfg.telegramDefaultSend) { $cfg.telegramDefaultSend = $true; $changed = $true }
  if ($changed) {
    Write-JsonFile -Path $path -Payload $cfg
  }
  return $cfg
}

function Get-LauncherPreferences {
  Ensure-CodrexDirs
  $path = Get-LauncherStatePath
  $prefs = Read-JsonFile -Path $path
  if (-not $prefs) {
    $prefs = [ordered]@{
      preferred_pair_route = "tailscale"
      advanced_visible = $true
    }
    Write-JsonFile -Path $path -Payload $prefs
  }
  if (-not $prefs.preferred_pair_route) { $prefs.preferred_pair_route = "tailscale" }
  if ($null -eq $prefs.advanced_visible) { $prefs.advanced_visible = $true }
  return $prefs
}

function Save-LauncherPreferences {
  param(
    [Parameter(Mandatory = $true)]
    [string]$PreferredPairRoute,
    [Parameter(Mandatory = $true)]
    [bool]$AdvancedVisible
  )
  $payload = [ordered]@{
    preferred_pair_route = $PreferredPairRoute
    advanced_visible = $AdvancedVisible
  }
  Write-JsonFile -Path (Get-LauncherStatePath) -Payload $payload
}

function Get-LanIpv4 {
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
  } catch {
  }
  return "127.0.0.1"
}

function Get-TailscaleIpv4 {
  try {
    $matches = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
      Where-Object { $_.IPAddress -like "100.*" } |
      Select-Object -First 1 -ExpandProperty IPAddress
    if ($matches) {
      return [string]$matches
    }
  } catch {
  }
  return ""
}

function Get-PreferredNetworkUrl {
  param(
    [Parameter(Mandatory = $true)]
    [int]$Port,
    [string]$PreferredRoute = ""
  )

  $route = $PreferredRoute
  if (-not $route) {
    $route = [string](Get-LauncherPreferences).preferred_pair_route
  }
  $lan = Get-LanIpv4
  $tailscale = Get-TailscaleIpv4
  $chosen = if ($route -eq "tailscale" -and $tailscale) { $tailscale } else { $lan }
  return [ordered]@{
    selected_pair_route = $route
    lan_ip = $lan
    tailscale_ip = $tailscale
    local_url = ("http://127.0.0.1:{0}/" -f $Port)
    network_url = if ($chosen) { "http://{0}:{1}/" -f $chosen, $Port } else { "" }
  }
}

function Get-ProcessInfoById {
  param([int]$ProcessId)
  try {
    return Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $ProcessId) -ErrorAction Stop
  } catch {
    return $null
  }
}

function Get-ControllerListenInfo {
  param([int]$Port)
  try {
    $tcp = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
  } catch {
    return $null
  }
  if (-not $tcp) { return $null }
  $proc = Get-ProcessInfoById -ProcessId $tcp.OwningProcess
  return [ordered]@{
    local_address = [string]$tcp.LocalAddress
    local_port = [int]$tcp.LocalPort
    state = [string]$tcp.State
    owning_process = [int]$tcp.OwningProcess
    process_name = if ($proc) { [string]$proc.Name } else { "" }
    command_line_tail = if ($proc -and $proc.CommandLine) { [string]$proc.CommandLine } else { "" }
  }
}

function Test-ControllerReady {
  param([int]$Port)
  try {
    $resp = Invoke-WebRequest -UseBasicParsing -Uri ("http://127.0.0.1:{0}/auth/status" -f $Port) -TimeoutSec 2
    return ($resp.StatusCode -eq 200)
  } catch {
    return $false
  }
}

function Invoke-ControllerJson {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [int]$Port = 48787,
    [string]$Method = "GET",
    [hashtable]$Headers = @{},
    [string]$Body = ""
  )
  $uri = "http://127.0.0.1:{0}{1}" -f $Port, $Path
  if ($Method -eq "GET") {
    return Invoke-RestMethod -UseBasicParsing -Uri $uri -Headers $Headers -TimeoutSec 5
  }
  return Invoke-RestMethod -UseBasicParsing -Uri $uri -Method $Method -Headers $Headers -Body $Body -TimeoutSec 5 -ContentType "application/json"
}

function Get-RepoRevision {
  $root = Get-RepoRoot
  $gitDir = Join-Path $root ".git"
  if (Test-Path -LiteralPath $gitDir) {
    try {
      $rev = (& git -C $root rev-parse --short HEAD 2>$null)
      if ($LASTEXITCODE -eq 0 -and $rev) {
        return ($rev | Select-Object -First 1)
      }
    } catch {
    }
  }
  $last = Read-JsonFile -Path (Get-LastActionPath)
  if ($last -and $last.repo_rev) {
    return [string]$last.repo_rev
  }
  return ""
}

function Get-ActiveCodexAccount {
  $script = "/mnt/d/codex-remote-ui/tools/wsl/codex-account.py current --json"
  try {
    $raw = & wsl.exe bash -lc $script
    if ($LASTEXITCODE -ne 0 -or -not $raw) {
      return $null
    }
    return (($raw -join "`n") | ConvertFrom-Json)
  } catch {
    return $null
  }
}

function Get-SessionAccountBindings {
  $path = Join-Path (Get-StateDir) "session-accounts.json"
  $payload = Read-JsonFile -Path $path
  if ($payload -and $payload.sessions) {
    return $payload.sessions.PSObject.Properties | ForEach-Object {
      [ordered]@{
        session = $_.Name
        account_id = [string]$_.Value.account_id
        account_label = [string]$_.Value.account_label
        codex_home = [string]$_.Value.codex_home
      }
    }
  }
  return @()
}

function Write-LauncherEvent {
  param(
    [string]$Level,
    [string]$Source,
    [string]$Action,
    [string]$Message,
    $Context = $null
  )

  Ensure-CodrexDirs
  $ts = (Get-Date).ToString("o")
  $line = "[{0}] level={1} source={2} action={3} message=""{4}""" -f $ts, $Level, $Source, $Action, ($Message -replace '"', "'")
  if ($null -ne $Context) {
    $json = ($Context | ConvertTo-Json -Compress -Depth 12)
    $line += " context=$json"
  }
  Add-Content -LiteralPath (Get-LauncherEventsPath) -Value $line -Encoding UTF8
}

function Write-ActionLog {
  param(
    [Parameter(Mandatory = $true)]
    [string]$ActionId,
    [Parameter(Mandatory = $true)]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$Source,
    [Parameter(Mandatory = $true)]
    $Payload
  )

  Ensure-CodrexDirs
  $stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
  $file = Join-Path (Get-ActionLogsDir) ("{0}-{1}-{2}.json" -f $stamp, $Action, $ActionId.Substring(0, 8))
  Write-JsonFile -Path $file -Payload $Payload
  Write-JsonFile -Path (Get-LastActionPath) -Payload $Payload
  if ($Payload.ok -eq $false) {
    Write-JsonFile -Path (Get-LastErrorPath) -Payload $Payload
  }
  return $file
}

function Get-RuntimeStatus {
  $cfg = Get-ControllerConfig
  $net = Get-PreferredNetworkUrl -Port ([int]$cfg.port)
  $listen = Get-ControllerListenInfo -Port ([int]$cfg.port)
  $sessionFile = Get-SessionFilePath
  $sessionPresent = Test-Path -LiteralPath $sessionFile
  $active = Get-ActiveCodexAccount
  $bindings = Get-SessionAccountBindings
  $repoRoot = Get-RepoRoot
  $repoRev = Get-RepoRevision
  $logsDir = Get-LogsDir

  $status = "stopped"
  $detail = "No active controller."
  $appReady = $false
  $appVersion = ""
  $uiMode = "offline"
  $controllerPid = $null
  $controllerPids = @()

  if ($listen) {
    $controllerPid = [int]$listen.owning_process
    $controllerPids = @($controllerPid)
    if (Test-ControllerReady -Port ([int]$cfg.port)) {
      $status = if ($sessionPresent) { "running" } else { "checking" }
      $detail = if ($sessionPresent) { "Codrex app is ready." } else { "Controller process is active and readiness is settling." }
      $appReady = $true
      $appVersion = "recovered-2026.03.26"
      $uiMode = if ($sessionPresent) { "built" } else { "offline" }
    } else {
      $status = if ($sessionPresent) { "recovering" } else { "checking" }
      $detail = if ($sessionPresent) {
        "Runtime session file exists without a live controller."
      } else {
        "Controller process is active and runtime session is absent. Readiness is still settling."
      }
    }
  } elseif ($sessionPresent) {
    $status = "recovering"
    $detail = "Runtime session file exists without a live controller."
  }

  return [ordered]@{
    ok = $true
    action = "status"
    status = $status
    detail = $detail
    repo_root = $repoRoot
    repo_rev = $repoRev
    runtime_dir = (Get-RuntimeDir)
    logs_dir = $logsDir
    controller_port = [int]$cfg.port
    controller_pid = $controllerPid
    controller_pids = $controllerPids
    duplicate_controllers = ($controllerPids.Count -gt 1)
    session_present = $sessionPresent
    session_file = $sessionFile
    app_ready = $appReady
    app_version = $appVersion
    ui_mode = $uiMode
    local_url = $net.local_url
    network_url = $net.network_url
    lan_ip = $net.lan_ip
    tailscale_ip = $net.tailscale_ip
    selected_pair_route = $net.selected_pair_route
    active_account_id = if ($active) { [string]$active.active_account_id } else { "" }
    active_account_label = if ($active) { [string]$active.label } else { "" }
    active_codex_home = if ($active) { [string]$active.codex_home } else { "" }
    account_bindings = $bindings
  }
}
