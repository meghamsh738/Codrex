param(
  [int]$UiPort = 4312,
  [switch]$OpenFirewall,
  [switch]$SkipUiInstall
)

$ErrorActionPreference = "Stop"

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
  if (-not (Test-Path $ConfigPath)) { return 8787 }
  try {
    $cfg = Get-Content -Path $ConfigPath -Raw | ConvertFrom-Json
    if ($cfg -and $cfg.port) {
      return [int]$cfg.port
    }
  } catch {}
  return 8787
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

$root = Split-Path -Parent $PSCommandPath
$uiRoot = Join-Path $root "ui"
$logsDir = Join-Path $root "logs"
$configPath = Join-Path $root "controller.config.json"
$sessionPath = Join-Path $logsDir "mobile.session.json"
$uiOutLog = Join-Path $logsDir "ui.out.log"
$uiErrLog = Join-Path $logsDir "ui.err.log"

if (-not (Test-Path $uiRoot)) {
  throw "UI folder not found at $uiRoot"
}
if (-not (Test-Path $logsDir)) {
  New-Item -Path $logsDir -ItemType Directory -Force | Out-Null
}

$controllerPort = Read-ControllerPort -ConfigPath $configPath

$startControllerScript = Join-Path $root "start-controller.ps1"
if (-not (Test-Path $startControllerScript)) {
  throw "Missing start script at $startControllerScript"
}

$controllerArgs = @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", $startControllerScript,
  "-Port", [string]$controllerPort,
  "-UiPort", [string]$UiPort
)
if ($OpenFirewall) {
  $controllerArgs += "-OpenFirewall"
}

Write-Host "Starting controller..."
& powershell.exe @controllerArgs

Ensure-UiDependencies -UiRoot $uiRoot -SkipInstall:$SkipUiInstall

$uiPid = $null
$existingUiOwners = Get-UiOwnerInfo -Port $UiPort
if ($existingUiOwners.Count -gt 0) {
  $viteOwner = $existingUiOwners | Where-Object { $_.CommandLine -and $_.CommandLine -match "vite" } | Select-Object -First 1
  if ($viteOwner) {
    $uiPid = [int]$viteOwner.ProcessId
    Write-Host "UI already running on port $UiPort (PID $uiPid). Reusing existing process."
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

  Write-Host "Starting mobile UI on port $UiPort..."
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
    Write-Host "UI failed to start. Recent logs:"
    if (Test-Path $uiErrTarget) { Get-Content $uiErrTarget -Tail 80 }
    if (Test-Path $uiOutTarget) { Get-Content $uiOutTarget -Tail 80 }
    throw "UI startup failed."
  }
}

if ($OpenFirewall) {
  Ensure-FirewallRuleForPort -Port $UiPort -RuleName ("Codrex Mobile UI {0}" -f $UiPort)
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
  ui_port = $UiPort
  ui_pid = $uiPid
}
$sessionData | ConvertTo-Json | Set-Content -Path $sessionPath -Encoding UTF8

Write-Host ""
Write-Host "Mobile stack ready."
Write-Host ("Controller URL: http://{0}:{1}" -f $lanIp, $controllerPort)
Write-Host ("UI Local URL:   http://127.0.0.1:{0}" -f $UiPort)
if ($lanIp -and $lanIp -ne "127.0.0.1") {
  Write-Host ("UI Network URL: http://{0}:{1}" -f $lanIp, $UiPort)
}
Write-Host ("Controller PID: {0}" -f ($(if ($controllerPid) { $controllerPid } else { "unknown" })))
Write-Host ("UI PID:         {0}" -f ($(if ($uiPid) { $uiPid } else { "unknown" })))
Write-Host ("Session file:   {0}" -f $sessionPath)
if (-not $OpenFirewall) {
  Write-Host "Tip: if phone/tablet cannot open network URL, rerun with -OpenFirewall."
}
