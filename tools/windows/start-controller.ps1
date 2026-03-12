param(
  [int]$Port = 48787,
  [int]$UiPort = 54312,
  [string]$Distro = "Ubuntu",
  [string]$Workdir = "/home/megha/codrex-work",
  [string]$FileRoot = "/home/megha/codrex-work",
  [switch]$OpenFirewall
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

function New-SecureToken([int]$ByteCount = 32) {
  $bytes = New-Object byte[] $ByteCount
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  $rng.GetBytes($bytes)
  $rng.Dispose()
  return ([Convert]::ToBase64String($bytes)).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function Mask-Secret {
  param(
    [string]$Value
  )
  if (-not $Value) { return "" }
  if ($Value.Length -le 12) { return ("*" * $Value.Length) }
  $head = $Value.Substring(0, 6)
  $tail = $Value.Substring($Value.Length - 4)
  return "$head...$tail"
}

function Convert-ToBoolean {
  param(
    [object]$Value,
    [bool]$Default = $false
  )
  if ($null -eq $Value) { return $Default }
  if ($Value -is [bool]) { return [bool]$Value }
  $text = "$Value"
  if ($null -eq $text) { return $Default }
  $norm = $text.Trim().ToLowerInvariant()
  if ($norm -in @("1", "true", "yes", "on")) { return $true }
  if ($norm -in @("0", "false", "no", "off")) { return $false }
  return $Default
}

function Convert-WindowsPathToWsl {
  param(
    [string]$WindowsPath
  )
  if (-not $WindowsPath) { return "" }
  $norm = $WindowsPath -replace '\\', '/'
  if ($norm -match '^([A-Za-z]):/(.*)$') {
    $drive = $matches[1].ToLower()
    $rest = $matches[2]
    return "/mnt/$drive/$rest"
  }
  return $norm
}

function Ensure-CodrexSendHelper {
  param(
    [string]$RepoRoot,
    [string]$Distro
  )
  try {
    $repoWsl = Convert-WindowsPathToWsl -WindowsPath $RepoRoot
    if (-not $repoWsl) { return }
    $helperWsl = "$repoWsl/tools/codrex-send.py"
    $installCmd = @"
set -e
if [ ! -f '$helperWsl' ]; then
  exit 0
fi
mkdir -p ~/.local/bin
ln -sf '$helperWsl' ~/.local/bin/codrex-send
chmod +x '$helperWsl' ~/.local/bin/codrex-send >/dev/null 2>&1 || true
"@
    & wsl.exe -d $Distro -- bash -lc $installCmd | Out-Null
  } catch {
    Write-Host "Warning: could not install codrex-send helper in WSL ($($_.Exception.Message))."
  }
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
      if ($ip) { return $ip }
    }
  } catch {}
  try {
    $line = (ipconfig | Select-String "IPv4 Address").Line | Select-Object -First 1
    if ($line -match ":\s*([0-9\.]+)\s*$") { return $matches[1] }
  } catch {}
  return "127.0.0.1"
}

function Get-PortOwners {
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

function Test-CodrexControllerOwner {
  param(
    [object[]]$Owners
  )
  foreach ($owner in ($Owners | Where-Object { $_ })) {
    $cmd = [string]$owner.CommandLine
    if ($cmd -and $cmd -match "app\.server:app") {
      return $true
    }
  }
  return $false
}

function Resolve-CodrexControllerPort {
  param(
    [int]$PreferredPort
  )
  $candidates = [System.Collections.Generic.List[int]]::new()
  foreach ($port in @($PreferredPort, $script:DefaultControllerPort)) {
    if ($port -gt 0 -and -not $candidates.Contains([int]$port)) {
      $null = $candidates.Add([int]$port)
    }
  }
  for ($offset = 0; $offset -lt 20; $offset++) {
    $candidate = $script:DefaultControllerPort + $offset
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
    $owners = @(Get-PortOwners -Port $candidate)
    if ($owners.Count -eq 0) {
      return [int]$candidate
    }
    if (Test-CodrexControllerOwner -Owners $owners) {
      return [int]$candidate
    }
  }
  throw "Could not find a free controller port near $PreferredPort. Close the conflicting app or set a custom Codrex port."
}

function Test-ControllerReady {
  param(
    [string]$ProbeHost,
    [int]$Port,
    [string]$Token
  )
  $headers = @{}
  if ($Token) {
    $headers["x-auth-token"] = $Token
  }
  try {
    $resp = Invoke-WebRequest -UseBasicParsing -Headers $headers -Uri ("http://{0}:{1}/auth/status" -f $ProbeHost, $Port) -TimeoutSec 1
    return ($resp.StatusCode -eq 200)
  } catch {}
  return $false
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

$runtimeDir = Get-CodrexRuntimeDir -RepoRoot $root
$stateDir = Join-Path $runtimeDir "state"
$logsDir = Join-Path $runtimeDir "logs"
$configPath = Join-Path $root "controller.config.json"
$localConfigPath = Join-Path $stateDir "controller.config.local.json"
$legacyLocalConfigPath = Join-Path $root "controller.config.local.json"
$outLog = Join-Path $logsDir "controller.out.log"
$errLog = Join-Path $logsDir "controller.err.log"

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
$script:DiagSource = "start-controller"
$script:DiagBeforeControllerSnapshot = @()
$startupTimer = [System.Diagnostics.Stopwatch]::StartNew()

function Write-StartControllerDiagnostic {
  param(
    [bool]$Ok,
    [string]$Detail,
    [AllowNull()]
    [object]$Extra = $null
  )
  $lanIp = Get-PrimaryIPv4
  $payload = [ordered]@{
    ok = $Ok
    status = if ($Ok) { "completed" } else { "error" }
    detail = $Detail
    repo_root = $root
    runtime_dir = $runtimeDir
    logs_dir = $logsDir
    controller_port = [int]$cfg.port
    ui_port = [int]$UiPort
    selected_pair_route = Get-CodrexSelectedRouteFromState -RuntimeDir $runtimeDir
    local_url = ("http://127.0.0.1:{0}/" -f $cfg.port)
    network_url = if ($lanIp -and $lanIp -ne "127.0.0.1") { ("http://{0}:{1}/" -f $lanIp, $cfg.port) } else { "" }
    session_file = Join-Path $stateDir "mobile.session.json"
    controller_port_snapshot_before = @($script:DiagBeforeControllerSnapshot)
    controller_port_snapshot_after = Get-CodrexPortDiagnosticsSnapshot -Ports @([int]$cfg.port)
    linked_process_logs = [ordered]@{
      controller_stdout = $outLog
      controller_stderr = $errLog
      ui_stdout = Join-Path $logsDir "ui.out.log"
      ui_stderr = Join-Path $logsDir "ui.err.log"
    }
  }
  if ($null -ne $Extra) {
    foreach ($property in $Extra.PSObject.Properties) {
      $payload[$property.Name] = $property.Value
    }
  }
  $null = Write-CodrexActionLog -RuntimeDir $runtimeDir -Action $script:DiagActionName -Source $script:DiagSource -Payload $payload -ActionId $script:DiagActionId -IsError:(-not $Ok)
  $null = Write-CodrexEventLog -RuntimeDir $runtimeDir -Source $script:DiagSource -Action $script:DiagActionName -ActionId $script:DiagActionId -Level $(if ($Ok) { "info" } else { "error" }) -Message $Detail -Context @{
    controller_port = [int]$cfg.port
    ui_port = [int]$UiPort
    open_firewall = [bool]$OpenFirewall
  }
}

trap {
  $message = if ($_.Exception -and $_.Exception.Message) { [string]$_.Exception.Message } else { [string]$_ }
  Write-StartControllerDiagnostic -Ok:$false -Detail $message -Extra ([pscustomobject]@{
    failure_stage = "start-controller"
  })
  exit 1
}

# Load persisted controller config. Sensitive values are stored in local override file.
$cfg = [ordered]@{}
function Apply-LoadedConfig {
  param(
    [object]$Loaded
  )
  if ($null -eq $Loaded) { return }
  try {
    if ($Loaded.port) { $cfg.port = [int]$Loaded.port }
  } catch {}
  try {
    if ($Loaded.distro) { $cfg.distro = [string]$Loaded.distro }
  } catch {}
  try {
    if ($Loaded.workdir) { $cfg.workdir = [string]$Loaded.workdir }
  } catch {}
  try {
    if ($Loaded.fileRoot) { $cfg.fileRoot = [string]$Loaded.fileRoot }
  } catch {}
  try {
    if ($Loaded.token) { $cfg.token = [string]$Loaded.token }
  } catch {}
  try {
    $cfg.telegramDefaultSend = Convert-ToBoolean -Value $Loaded.telegramDefaultSend -Default $true
  } catch {}
}

if (Test-Path $configPath) {
  try {
    $raw = Get-Content $configPath -Raw
    if ($raw.Trim()) {
      Apply-LoadedConfig -Loaded ($raw | ConvertFrom-Json)
    }
  } catch {}
}
if (Test-Path $localConfigPath) {
  try {
    $rawLocal = Get-Content $localConfigPath -Raw
    if ($rawLocal.Trim()) {
      Apply-LoadedConfig -Loaded ($rawLocal | ConvertFrom-Json)
    }
  } catch {}
} elseif (Test-Path $legacyLocalConfigPath) {
  try {
    $rawLegacyLocal = Get-Content $legacyLocalConfigPath -Raw
    if ($rawLegacyLocal.Trim()) {
      Apply-LoadedConfig -Loaded ($rawLegacyLocal | ConvertFrom-Json)
    }
  } catch {}
}

if ($PSBoundParameters.ContainsKey("Port")) { $cfg.port = $Port }
if ($PSBoundParameters.ContainsKey("Distro")) { $cfg.distro = $Distro }
if ($PSBoundParameters.ContainsKey("Workdir")) { $cfg.workdir = $Workdir }
if ($PSBoundParameters.ContainsKey("FileRoot")) { $cfg.fileRoot = $FileRoot }

if (-not $cfg.port) { $cfg.port = $script:DefaultControllerPort }
if (-not $cfg.distro) { $cfg.distro = "Ubuntu" }
if (-not $cfg.workdir) { $cfg.workdir = "/home/megha/codrex-work" }
if (-not $cfg.fileRoot) { $cfg.fileRoot = $cfg.workdir }
if (-not $cfg.token -or $cfg.token.Length -lt 24) { $cfg.token = New-SecureToken }
$cfg.telegramDefaultSend = Convert-ToBoolean -Value $cfg.telegramDefaultSend -Default $true

if ((-not $PSBoundParameters.ContainsKey("Port")) -and ([int]$cfg.port -eq $script:LegacyControllerPort)) {
  $cfg.port = $script:DefaultControllerPort
}
$resolvedPort = Resolve-CodrexControllerPort -PreferredPort ([int]$cfg.port)
if ($resolvedPort -ne [int]$cfg.port) {
  Write-Host ("Codrex controller port {0} is busy. Using {1} instead." -f $cfg.port, $resolvedPort)
  $cfg.port = $resolvedPort
}
$script:DiagBeforeControllerSnapshot = Get-CodrexPortDiagnosticsSnapshot -Ports @([int]$cfg.port)
$null = Write-CodrexEventLog -RuntimeDir $runtimeDir -Source $script:DiagSource -Action $script:DiagActionName -ActionId $script:DiagActionId -Message "Starting controller script." -Context @{
  controller_port = [int]$cfg.port
  ui_port = [int]$UiPort
  distro = [string]$cfg.distro
  workdir = [string]$cfg.workdir
  file_root = [string]$cfg.fileRoot
  open_firewall = [bool]$OpenFirewall
}

$persistLocal = [ordered]@{
  port = [int]$cfg.port
  distro = [string]$cfg.distro
  workdir = [string]$cfg.workdir
  fileRoot = [string]$cfg.fileRoot
  token = [string]$cfg.token
  telegramDefaultSend = [bool]$cfg.telegramDefaultSend
}
$persistLocal | ConvertTo-Json | Set-Content -Path $localConfigPath -Encoding UTF8

# Ensure `codrex-send` helper exists inside WSL for Codex sessions.
Ensure-CodrexSendHelper -RepoRoot $root -Distro $cfg.distro

# Stop old controller processes on this port.
$pattern = "--port\s+$($cfg.port)\b"
$existing = Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and $_.CommandLine -match "app\.server:app" -and $_.CommandLine -match $pattern }
foreach ($p in $existing) {
  try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch {}
}

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  throw "Python executable not found at $python. Create the Windows venv in the repo root first."
  throw "Python executable not found at $python. Create venv in C:\codrex-remote-ui\.venv first."
}

$outLog = Resolve-LogTargetPath -Path $outLog
$errLog = Resolve-LogTargetPath -Path $errLog

$env:CODEX_AUTH_TOKEN = [string]$cfg.token
$env:CODEX_RUNTIME_DIR = [string]$runtimeDir
$env:CODEX_WSL_DISTRO = [string]$cfg.distro
$env:CODEX_WORKDIR = [string]$cfg.workdir
$env:CODEX_FILE_ROOT = [string]$cfg.fileRoot
$env:CODEX_MOBILE_UI_PORT = [string]$UiPort
$env:CODEX_TELEGRAM_DEFAULT_SEND = if ($cfg.telegramDefaultSend) { "1" } else { "0" }

$launchCommand = 'start "" /b "{0}" -m uvicorn app.server:app --host 0.0.0.0 --port {1} 1>>"{2}" 2>>"{3}"' -f $python, $cfg.port, $outLog, $errLog
$null = Start-Process -FilePath "cmd.exe" -ArgumentList @("/d", "/c", $launchCommand) -WorkingDirectory $root -WindowStyle Hidden -PassThru

# Wait until endpoint responds.
$ok = $false
$readyHost = ""
$probeHosts = @("127.0.0.1", "localhost") | Select-Object -Unique
for ($i = 0; $i -lt 40; $i++) {
  foreach ($h in $probeHosts) {
    if (Test-ControllerReady -ProbeHost $h -Port $cfg.port -Token $cfg.token) {
      $ok = $true
      $readyHost = $h
      break
    }
  }
  if ($ok) { break }
  Start-Sleep -Milliseconds 50
}

if (-not $ok) {
  Write-Host "Controller failed to start. Last error log:"
  if (Test-Path $errLog) { Get-Content $errLog -Tail 80 }
  try {
    $listeners = Get-NetTCPConnection -LocalPort $cfg.port -State Listen -ErrorAction SilentlyContinue
    if ($listeners) {
      Write-Host "Port listeners on $($cfg.port):"
      foreach ($l in $listeners | Sort-Object LocalAddress, OwningProcess) {
        $p = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $l.OwningProcess) -ErrorAction SilentlyContinue
        $pname = if ($p) { $p.Name } else { "unknown" }
        Write-Host ("  {0}:{1} PID={2} ({3})" -f $l.LocalAddress, $l.LocalPort, $l.OwningProcess, $pname)
      }
      Write-Host "Tip: another app on 127.0.0.1:$($cfg.port) can break localhost checks. Either stop it or use a different port for Codrex."
    }
  } catch {}
  throw "Startup failed."
}

if ($OpenFirewall) {
  $ruleName = "Codrex Remote Controller $($cfg.port)"
  try {
    $rule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if (-not $rule) {
      New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $cfg.port | Out-Null
    }
  } catch {
    Write-Host "Warning: firewall rule not applied ($($_.Exception.Message))."
  }
}

$ip = Get-PrimaryIPv4
$controllerProc = Get-PortOwners -Port ([int]$cfg.port) |
  Where-Object { $_.CommandLine -and $_.CommandLine -match "app\.server:app" } |
  Sort-Object ProcessId -Descending |
  Select-Object -First 1
$controllerPid = if ($controllerProc) { [int]$controllerProc.ProcessId } else { 0 }
Write-Host "Controller started."
Write-Host ("URL: http://{0}:{1}" -f $ip, $cfg.port)
if ($readyHost) {
  Write-Host ("Readiness probe: http://{0}:{1}/auth/status" -f $readyHost, $cfg.port)
}
Write-Host ("Token: {0}" -f (Mask-Secret -Value ([string]$cfg.token)))
Write-Host ("Token file: {0}" -f $localConfigPath)
Write-Host ("Runtime dir: {0}" -f $runtimeDir)
Write-Host "PID: $controllerPid"
Write-Host "Logs: $outLog"
Write-StartControllerDiagnostic -Ok:$true -Detail "Controller started." -Extra ([pscustomobject]@{
  controller_pid = $controllerPid
  ready_host = $readyHost
  open_firewall = [bool]$OpenFirewall
  log_stdout = $outLog
  log_stderr = $errLog
  controller_ready_ms = [int]$startupTimer.ElapsedMilliseconds
})
exit 0
