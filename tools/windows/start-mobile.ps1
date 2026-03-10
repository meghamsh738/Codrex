param(
  [int]$UiPort = 54312,
  [switch]$OpenFirewall,
  [switch]$SkipUiInstall,
  [switch]$DevUi
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $PSCommandPath
$root = (Resolve-Path (Join-Path $scriptRoot "..\..")).Path
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
    [string]$ConfigPath
  )
  if (-not (Test-Path $ConfigPath)) { return $script:DefaultControllerPort }
  try {
    $cfg = Get-Content -Path $ConfigPath -Raw | ConvertFrom-Json
    if ($cfg -and $cfg.port) {
      return [int]$cfg.port
    }
  } catch {}
  return $script:DefaultControllerPort
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

$controllerPort = Read-ControllerPort -ConfigPath $configPath
if ($controllerPort -eq $script:LegacyControllerPort) {
  $controllerPort = $script:DefaultControllerPort
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
    $controllerPort = Read-ControllerPort -ConfigPath $configPath
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

$controllerPort = Read-ControllerPort -ConfigPath $configPath

if ($OpenFirewall) {
  if ($DevUi) {
    Ensure-FirewallRuleForPort -Port $UiPort -RuleName ("Codrex Mobile UI {0}" -f $UiPort)
  }
}

$controllerPattern = "--port\s+$controllerPort\b"
$controllerProc = Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and $_.CommandLine -match "app\.server:app" -and $_.CommandLine -match $controllerPattern } |
  Sort-Object ProcessId -Descending |
  Select-Object -First 1
$controllerPid = if ($controllerProc) { [int]$controllerProc.ProcessId } else { $null }

$lanIp = Get-PrimaryIPv4
$sessionData = [ordered]@{
  started_at = (Get-Date).ToString("o")
  controller_port = $controllerPort
  controller_pid = $controllerPid
  ui_port = if ($DevUi) { $UiPort } else { $null }
  ui_pid = $uiPid
  ui_mode = if ($DevUi) { "dev" } else { "built" }
}
$sessionData | ConvertTo-Json | Set-Content -Path $sessionPath -Encoding UTF8

Write-Host ""
Write-Host "Mobile stack ready."
Write-Host ("Controller URL: http://{0}:{1}" -f $lanIp, $controllerPort)
Write-Host ("App Local URL:  http://127.0.0.1:{0}" -f $controllerPort)
if ($lanIp -and $lanIp -ne "127.0.0.1") {
  Write-Host ("App Network URL: http://{0}:{1}" -f $lanIp, $controllerPort)
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
