param(
  [int]$Port = 8787,
  [string]$Distro = "Ubuntu",
  [string]$Workdir = "/home/megha/codrex-work",
  [string]$FileRoot = "/home/megha/codrex-work",
  [switch]$OpenFirewall
)

$ErrorActionPreference = "Stop"

function New-SecureToken([int]$ByteCount = 32) {
  $bytes = New-Object byte[] $ByteCount
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  $rng.GetBytes($bytes)
  $rng.Dispose()
  return ([Convert]::ToBase64String($bytes)).TrimEnd("=").Replace("+", "-").Replace("/", "_")
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

$root = Split-Path -Parent $PSCommandPath
$configPath = Join-Path $root "controller.config.json"
$logsDir = Join-Path $root "logs"
$outLog = Join-Path $logsDir "controller.out.log"
$errLog = Join-Path $logsDir "controller.err.log"

if (-not (Test-Path $logsDir)) {
  New-Item -Path $logsDir -ItemType Directory -Force | Out-Null
}

# Load or initialize persisted controller config.
$cfg = [ordered]@{}
if (Test-Path $configPath) {
  try {
    $raw = Get-Content $configPath -Raw
    if ($raw.Trim()) {
      $loaded = $raw | ConvertFrom-Json
      if ($null -ne $loaded) {
        $cfg.port = [int]$loaded.port
        $cfg.distro = [string]$loaded.distro
        $cfg.workdir = [string]$loaded.workdir
        $cfg.fileRoot = [string]$loaded.fileRoot
        $cfg.token = [string]$loaded.token
      }
    }
  } catch {}
}

if ($PSBoundParameters.ContainsKey("Port")) { $cfg.port = $Port }
if ($PSBoundParameters.ContainsKey("Distro")) { $cfg.distro = $Distro }
if ($PSBoundParameters.ContainsKey("Workdir")) { $cfg.workdir = $Workdir }
if ($PSBoundParameters.ContainsKey("FileRoot")) { $cfg.fileRoot = $FileRoot }

if (-not $cfg.port) { $cfg.port = 8787 }
if (-not $cfg.distro) { $cfg.distro = "Ubuntu" }
if (-not $cfg.workdir) { $cfg.workdir = "/home/megha/codrex-work" }
if (-not $cfg.fileRoot) { $cfg.fileRoot = $cfg.workdir }
if (-not $cfg.token -or $cfg.token.Length -lt 24) { $cfg.token = New-SecureToken }

$cfg | ConvertTo-Json | Set-Content -Path $configPath -Encoding UTF8

# Stop old controller processes on this port.
$pattern = "--port\s+$($cfg.port)\b"
$existing = Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and $_.CommandLine -match "app\.server:app" -and $_.CommandLine -match $pattern }
foreach ($p in $existing) {
  try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch {}
}

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  throw "Python executable not found at $python. Create venv in C:\codrex-remote-ui\.venv first."
}

if (Test-Path $outLog) { Remove-Item $outLog -Force }
if (Test-Path $errLog) { Remove-Item $errLog -Force }

$env:CODEX_AUTH_TOKEN = [string]$cfg.token
$env:CODEX_WSL_DISTRO = [string]$cfg.distro
$env:CODEX_WORKDIR = [string]$cfg.workdir
$env:CODEX_FILE_ROOT = [string]$cfg.fileRoot

$args = @("-m", "uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", [string]$cfg.port)
$proc = Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru

# Wait until endpoint responds.
$ok = $false
for ($i = 0; $i -lt 20; $i++) {
  Start-Sleep -Milliseconds 300
  try {
    $resp = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$($cfg.port)/auth/status" -TimeoutSec 2
    if ($resp.StatusCode -eq 200) { $ok = $true; break }
  } catch {}
}

if (-not $ok) {
  Write-Host "Controller failed to start. Last error log:"
  if (Test-Path $errLog) { Get-Content $errLog -Tail 80 }
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
Write-Host "Controller started."
Write-Host ("URL: http://{0}:{1}" -f $ip, $cfg.port)
Write-Host "Token: $($cfg.token)"
Write-Host "PID: $($proc.Id)"
Write-Host "Logs: $outLog"
