param(
  [int]$UiPort = 54312,
  [switch]$OpenFirewall,
  [switch]$SkipUiInstall,
  [switch]$DevUi
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $PSCommandPath
$root = (Resolve-Path (Join-Path $scriptRoot "..\..")).Path
$diagnosticsScript = Join-Path $scriptRoot "codrex-diagnostics.ps1"
if (Test-Path $diagnosticsScript) {
  . $diagnosticsScript
}
$script:DefaultControllerPort = 48787
$script:LegacyControllerPort = 8787
$script:DefaultDevUiPort = 54312

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

function Read-ControllerPort {
  param(
    [string]$ConfigPath,
    [string]$LocalConfigPath = "",
    [string]$LegacyLocalConfigPath = ""
  )
  foreach ($candidate in @($LocalConfigPath, $LegacyLocalConfigPath, $ConfigPath)) {
    if (-not $candidate -or -not (Test-Path $candidate)) { continue }
    try {
      $cfg = Get-Content -Path $candidate -Raw | ConvertFrom-Json
      if ($cfg -and $cfg.port) {
        return [int]$cfg.port
      }
    } catch {}
  }
  return $script:DefaultControllerPort
}

function Read-SessionData {
  param(
    [string]$Path
  )
  if (-not (Test-Path $Path)) {
    return $null
  }
  try {
    return (Get-Content -Path $Path -Raw | ConvertFrom-Json)
  } catch {}
  return $null
}

function Ensure-UiDependencies {
  param(
    [string]$UiRoot,
    [switch]$SkipInstall
  )
  $viteCmd = Join-Path $UiRoot "node_modules\.bin\vite.cmd"
  if (Test-Path $viteCmd) {
    return
  }
  if ($SkipInstall) {
    throw "UI dependencies are missing ($viteCmd) and -SkipUiInstall was passed."
  }
  $npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
  if (-not $npmCmd) {
    throw "npm.cmd not found. Install Node.js/npm on Windows first."
  }
  Write-Host "Installing UI dependencies in $UiRoot ..."
  & $npmCmd install --prefix $UiRoot
  if (-not (Test-Path $viteCmd)) {
    throw "UI dependency install completed but vite.cmd is still missing at $viteCmd"
  }
}

function Ensure-BuiltUi {
  param(
    [string]$UiRoot
  )
  $builtIndex = Join-Path $UiRoot "dist\index.html"
  if (-not (Test-Path $builtIndex)) {
    throw "Built UI missing at $builtIndex. Run Setup.cmd or 'npm run build' in the ui folder first."
  }
}

function Test-HttpReady {
  param(
    [string]$Url
  )
  try {
    $resp = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
    return ($resp.StatusCode -eq 200)
  } catch {}
  return $false
}

function Get-AppHealth {
  param(
    [int]$Port
  )
  try {
    return Invoke-RestMethod -UseBasicParsing -Uri ("http://127.0.0.1:{0}/app/health" -f $Port) -TimeoutSec 2
  } catch {}
  return $null
}

function Get-UiOwnerInfo {
  param(
    [int]$Port
  )
  try {
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  } catch {
    return @()
  }
  if (-not $listeners) {
    return @()
  }
  $owners = @()
  foreach ($listener in ($listeners | Select-Object -Unique OwningProcess)) {
    $procId = [int]$listener.OwningProcess
    $proc = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $procId) -ErrorAction SilentlyContinue
    if ($proc) {
      $owners += $proc
    }
  }
  return $owners
}

function Get-ProcessIdByListeningPort {
  param(
    [int]$Port
  )
  if ($Port -le 0) {
    return $null
  }
  try {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
      Select-Object -First 1
    if ($listener -and $listener.OwningProcess) {
      return [int]$listener.OwningProcess
    }
  } catch {}
  return $null
}

function Resolve-DevUiPort {
  param(
    [int]$PreferredPort
  )
  $candidates = [System.Collections.Generic.List[int]]::new()
  foreach ($port in @($PreferredPort, $script:DefaultDevUiPort)) {
    if ($port -gt 0 -and -not $candidates.Contains([int]$port)) {
      $null = $candidates.Add([int]$port)
    }
  }
  for ($offset = 0; $offset -lt 20; $offset++) {
    $candidate = $script:DefaultDevUiPort + $offset
    if (-not $candidates.Contains([int]$candidate)) {
      $null = $candidates.Add([int]$candidate)
    }
  }
  for ($offset = 1; $offset -le 20; $offset++) {
    $candidate = $PreferredPort + $offset
    if ($candidate -gt 0 -and -not $candidates.Contains([int]$candidate)) {
      $null = $candidates.Add([int]$candidate)
    }
  }

  foreach ($candidate in $candidates) {
    $owners = @(Get-UiOwnerInfo -Port $candidate)
    if ($owners.Count -eq 0) {
      return [int]$candidate
    }
    $viteOwner = $owners | Where-Object { $_.CommandLine -and $_.CommandLine -match "vite" } | Select-Object -First 1
    if ($viteOwner) {
      return [int]$candidate
    }
  }
  throw "Could not find a free dev UI port near $PreferredPort."
}

function Ensure-FirewallRuleForPort {
  param(
    [int]$Port,
    [string]$RuleName
  )
  try {
    $rule = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
    if (-not $rule) {
      New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port | Out-Null
    }
  } catch {
    Write-Host "Warning: firewall rule '$RuleName' not applied ($($_.Exception.Message))."
  }
}

function Resolve-LogTargetPath {
  param(
    [string]$Path
  )
  if (-not $Path) {
    return ""
  }
  if (-not (Test-Path $Path)) {
    return $Path
  }
  try {
    Remove-Item $Path -Force -ErrorAction Stop
    return $Path
  } catch {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $alt = "{0}.{1}.run.log" -f $Path, $stamp
    Write-Host "Warning: log file '$Path' is locked. Using '$alt' for this run."
    return $alt
  }
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

$uiRoot = Join-Path $root "ui"
$runtimeDir = Get-CodrexRuntimeDir -RepoRoot $root
$stateDir = Join-Path $runtimeDir "state"
$logsDir = Join-Path $runtimeDir "logs"
$configPath = Join-Path $root "controller.config.json"
$localConfigPath = Join-Path $stateDir "controller.config.local.json"
$legacyLocalConfigPath = Join-Path $root "controller.config.local.json"
$sessionPath = Join-Path $stateDir "mobile.session.json"
$uiOutLog = Join-Path $logsDir "ui.out.log"
$uiErrLog = Join-Path $logsDir "ui.err.log"

if (-not (Test-Path $uiRoot)) {
  throw "UI folder not found at $uiRoot"
}
foreach ($dir in @($runtimeDir, $stateDir, $logsDir)) {
  if (-not (Test-Path $dir)) {
    New-Item -Path $dir -ItemType Directory -Force | Out-Null
  }
}
$script:DiagnosticsLayout = Ensure-CodrexDiagnosticsLayout -RuntimeDir $runtimeDir
$script:DiagActionId = Get-CodrexCurrentActionId
if (-not $script:DiagActionId) {
  $script:DiagActionId = New-CodrexActionId
}
$script:DiagActionName = Get-CodrexCurrentActionName
if (-not $script:DiagActionName) {
  $script:DiagActionName = "start"
}
$script:DiagSource = "start-mobile"
$script:DiagBeforeSessionState = if ((Read-SessionData -Path $sessionPath) -or (Read-SessionData -Path (Join-Path (Join-Path $root "logs") "mobile.session.json"))) { "present" } else { "missing" }
$script:DiagBeforeControllerSnapshot = @()
$script:DiagBeforeUiSnapshot = @()
$script:DiagLinkedLogs = [ordered]@{
  controller_stdout = Join-Path $logsDir "controller.out.log"
  controller_stderr = Join-Path $logsDir "controller.err.log"
  ui_stdout = $uiOutLog
  ui_stderr = $uiErrLog
}

function Write-StartMobileDiagnostic {
  param(
    [bool]$Ok,
    [string]$Detail,
    [AllowNull()]
    [object]$Extra = $null
  )
  $currentSession = Read-SessionData -Path $sessionPath
  $lanIp = Get-PrimaryIPv4
  $payload = [ordered]@{
    ok = $Ok
    status = if ($Ok) { "completed" } else { "error" }
    detail = $Detail
    repo_root = $root
    runtime_dir = $runtimeDir
    logs_dir = $logsDir
    controller_port = $controllerPort
    ui_port = $UiPort
    ui_mode = if ($DevUi) { "dev" } else { "built" }
    selected_pair_route = Get-CodrexSelectedRouteFromState -RuntimeDir $runtimeDir
    local_url = if ($controllerPort -gt 0) { ("http://127.0.0.1:{0}/" -f $controllerPort) } else { "" }
    network_url = if ($lanIp -and $lanIp -ne "127.0.0.1" -and $controllerPort -gt 0) { ("http://{0}:{1}/" -f $lanIp, $controllerPort) } else { "" }
    session_file = $sessionPath
    session_state_before = $script:DiagBeforeSessionState
    session_state_after = if ($currentSession) { "present" } else { "missing" }
    controller_port_snapshot_before = @($script:DiagBeforeControllerSnapshot)
    controller_port_snapshot_after = Get-CodrexPortDiagnosticsSnapshot -Ports @($controllerPort)
    ui_port_snapshot_before = @($script:DiagBeforeUiSnapshot)
    ui_port_snapshot_after = Get-CodrexPortDiagnosticsSnapshot -Ports @($UiPort)
    linked_process_logs = $script:DiagLinkedLogs
  }
  if ($null -ne $Extra) {
    foreach ($property in $Extra.PSObject.Properties) {
      $payload[$property.Name] = $property.Value
    }
  }
  $null = Write-CodrexActionLog -RuntimeDir $runtimeDir -Action $script:DiagActionName -Source $script:DiagSource -Payload $payload -ActionId $script:DiagActionId -IsError:(-not $Ok)
  $null = Write-CodrexEventLog -RuntimeDir $runtimeDir -Source $script:DiagSource -Action $script:DiagActionName -ActionId $script:DiagActionId -Level $(if ($Ok) { "info" } else { "error" }) -Message $Detail -Context @{
    controller_port = $controllerPort
    ui_port = $UiPort
    ui_mode = if ($DevUi) { "dev" } else { "built" }
    session_state_after = if ($currentSession) { "present" } else { "missing" }
  }
}

trap {
  $message = if ($_.Exception -and $_.Exception.Message) { [string]$_.Exception.Message } else { [string]$_ }
  Write-StartMobileDiagnostic -Ok:$false -Detail $message -Extra ([pscustomobject]@{
    failure_stage = "start-mobile"
  })
  exit 1
}

$controllerPort = Read-ControllerPort -ConfigPath $configPath -LocalConfigPath $localConfigPath -LegacyLocalConfigPath $legacyLocalConfigPath
if ($controllerPort -eq $script:LegacyControllerPort) {
  $controllerPort = $script:DefaultControllerPort
}
$script:DiagBeforeControllerSnapshot = Get-CodrexPortDiagnosticsSnapshot -Ports @($controllerPort)
$script:DiagBeforeUiSnapshot = Get-CodrexPortDiagnosticsSnapshot -Ports @($UiPort)
$null = Write-CodrexEventLog -RuntimeDir $runtimeDir -Source $script:DiagSource -Action $script:DiagActionName -ActionId $script:DiagActionId -Message "Starting mobile stack script." -Context @{
  controller_port = $controllerPort
  ui_port = $UiPort
  dev_ui = [bool]$DevUi
  open_firewall = [bool]$OpenFirewall
  skip_ui_install = [bool]$SkipUiInstall
  session_state_before = $script:DiagBeforeSessionState
}

if ($DevUi) {
  $resolvedUiPort = Resolve-DevUiPort -PreferredPort $UiPort
  if ($resolvedUiPort -ne $UiPort) {
    Write-Host ("Codrex dev UI port {0} is busy. Using {1} instead." -f $UiPort, $resolvedUiPort)
    $UiPort = $resolvedUiPort
  }
}

$startControllerScript = Join-Path $scriptRoot "start-controller.ps1"
if (-not (Test-Path $startControllerScript)) {
  throw "Missing start script at $startControllerScript"
}

$controllerUiPort = if ($DevUi) { $UiPort } else { $controllerPort }
$controllerArgs = @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", $startControllerScript,
  "-Port", [string]$controllerPort,
  "-UiPort", [string]$controllerUiPort
)
if ($OpenFirewall) {
  $controllerArgs += "-OpenFirewall"
}

if ($DevUi) {
  Ensure-UiDependencies -UiRoot $uiRoot -SkipInstall:$SkipUiInstall
} else {
  Ensure-BuiltUi -UiRoot $uiRoot
}

Write-Host "Starting controller..."
& powershell.exe @controllerArgs

$uiPid = $null
if ($DevUi) {
  $existingUiOwners = Get-UiOwnerInfo -Port $UiPort
  if ($existingUiOwners.Count -gt 0) {
    $viteOwner = $existingUiOwners | Where-Object { $_.CommandLine -and $_.CommandLine -match "vite" } | Select-Object -First 1
    if ($viteOwner) {
      $uiPid = [int]$viteOwner.ProcessId
      Write-Host "Dev UI already running on port $UiPort (PID $uiPid). Reusing existing process."
    } else {
      $details = ($existingUiOwners | ForEach-Object { "PID=$($_.ProcessId) Name=$($_.Name)" }) -join "; "
      throw "Port $UiPort is already in use by another process. $details"
    }
  } else {
    $npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
    if (-not $npmCmd) {
      throw "npm.cmd not found. Install Node.js/npm on Windows first."
    }

    $uiOutTarget = Resolve-LogTargetPath -Path $uiOutLog
    $uiErrTarget = Resolve-LogTargetPath -Path $uiErrLog

    Write-Host "Starting dev UI on port $UiPort..."
    $uiProc = Start-Process -FilePath $npmCmd `
      -ArgumentList @("run", "dev", "--", "--host", "0.0.0.0", "--port", [string]$UiPort) `
      -WorkingDirectory $uiRoot `
      -WindowStyle Hidden `
      -RedirectStandardOutput $uiOutTarget `
      -RedirectStandardError $uiErrTarget `
      -PassThru
    $uiPid = [int]$uiProc.Id

    $uiReady = $false
    for ($i = 0; $i -lt 40; $i++) {
      Start-Sleep -Milliseconds 300
      if (Test-HttpReady -Url ("http://127.0.0.1:{0}/" -f $UiPort)) {
        $uiReady = $true
        break
      }
      if (-not (Get-Process -Id $uiPid -ErrorAction SilentlyContinue)) {
        break
      }
    }
    if (-not $uiReady) {
      try { Stop-Process -Id $uiPid -Force -ErrorAction SilentlyContinue } catch {}
      Write-Host "Dev UI failed to start. Recent logs:"
      if (Test-Path $uiErrTarget) { Get-Content $uiErrTarget -Tail 80 }
      if (Test-Path $uiOutTarget) { Get-Content $uiOutTarget -Tail 80 }
      throw "Dev UI startup failed."
    }
  }
} else {
  $appReady = $false
  $appHealth = $null
  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 300
    $controllerPort = Read-ControllerPort -ConfigPath $configPath -LocalConfigPath $localConfigPath -LegacyLocalConfigPath $legacyLocalConfigPath
    $appHealth = Get-AppHealth -Port $controllerPort
    if ($appHealth -and $appHealth.ok -and $appHealth.ui_mode -eq "built") {
      $appReady = $true
      break
    }
  }
  if (-not $appReady) {
    $detail = if ($appHealth -and $appHealth.detail) { [string]$appHealth.detail } else { "Controller app health never reached built mode." }
    throw "Built app startup failed. $detail"
  }
}

$controllerPort = Read-ControllerPort -ConfigPath $configPath -LocalConfigPath $localConfigPath -LegacyLocalConfigPath $legacyLocalConfigPath

if ($OpenFirewall) {
  if ($DevUi) {
    Ensure-FirewallRuleForPort -Port $UiPort -RuleName ("Codrex Mobile UI {0}" -f $UiPort)
  }
}

$controllerPid = Get-ProcessIdByListeningPort -Port $controllerPort

$lanIp = Get-PrimaryIPv4
$localAppUrl = ("http://127.0.0.1:{0}/" -f $controllerPort)
$networkAppUrl = if ($lanIp -and $lanIp -ne "127.0.0.1") { ("http://{0}:{1}/" -f $lanIp, $controllerPort) } else { "" }
$sessionData = [ordered]@{
  started_at = (Get-Date).ToString("o")
  controller_port = $controllerPort
  controller_pid = $controllerPid
  ui_port = if ($DevUi) { $UiPort } else { $null }
  ui_pid = $uiPid
  ui_mode = if ($DevUi) { "dev" } else { "built" }
  repo_root = $root
  runtime_dir = $runtimeDir
  session_file = $sessionPath
  app_url = $localAppUrl
  network_app_url = $networkAppUrl
}
$sessionData | ConvertTo-Json | Set-Content -Path $sessionPath -Encoding UTF8
$persistedSession = Read-SessionData -Path $sessionPath
if (-not $persistedSession -or [int]$persistedSession.controller_port -ne $controllerPort) {
  throw "Codrex runtime session file was not written correctly at $sessionPath"
}

Write-Host ""
Write-Host "Mobile stack ready."
Write-Host ("Controller URL: http://{0}:{1}" -f $lanIp, $controllerPort)
Write-Host ("App Local URL:  {0}" -f $localAppUrl.TrimEnd("/"))
if ($lanIp -and $lanIp -ne "127.0.0.1") {
  Write-Host ("App Network URL: {0}" -f $networkAppUrl.TrimEnd("/"))
}
if ($DevUi) {
  Write-Host ("Dev UI Local URL: http://127.0.0.1:{0}" -f $UiPort)
}
Write-Host ("Controller PID: {0}" -f ($(if ($controllerPid) { $controllerPid } else { "unknown" })))
Write-Host ("Dev UI PID:     {0}" -f ($(if ($uiPid) { $uiPid } else { "n/a" })))
Write-Host ("Session file:   {0}" -f $sessionPath)
Write-Host ("Runtime dir:    {0}" -f $runtimeDir)
if ((-not $OpenFirewall) -and ($lanIp -and $lanIp -ne "127.0.0.1")) {
  Write-Host "Tip: if phone/tablet cannot open network URL, rerun with -OpenFirewall."
}
Write-StartMobileDiagnostic -Ok:$true -Detail "Mobile stack ready." -Extra ([pscustomobject]@{
  controller_pid = $controllerPid
  ui_pid = $uiPid
  dev_ui = [bool]$DevUi
  open_firewall = [bool]$OpenFirewall
  session_written = [bool]$persistedSession
})
exit 0
