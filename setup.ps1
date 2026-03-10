param(
  [int]$Port = 48787,
  [string]$Distro = "Ubuntu",
  [string]$Workdir = "/home/megha/codrex-work",
  [string]$FileRoot = "/home/megha/codrex-work",
  [switch]$OpenFirewall
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSCommandPath
Set-Location $root

function Read-ControllerPort {
  param(
    [string]$ConfigPath,
    [int]$FallbackPort
  )
  if (-not (Test-Path $ConfigPath)) {
    return $FallbackPort
  }
  try {
    $cfg = Get-Content -Path $ConfigPath -Raw | ConvertFrom-Json
    if ($cfg -and $cfg.port) {
      return [int]$cfg.port
    }
  } catch {}
  return $FallbackPort
}

$configPath = Join-Path $root "controller.config.json"
$startMobileScript = Join-Path $root "tools\windows\start-mobile.ps1"
$launcherCmd = Join-Path $root "Codrex.cmd"
$summaryLines = New-Object System.Collections.Generic.List[string]
$setupFailed = $false

try {
  $pyCmd = Get-Command py -ErrorAction SilentlyContinue
  if (-not $pyCmd) {
    throw "Python launcher 'py' was not found. Install Python 3.11+ on Windows first."
  }

  $venvPython = Join-Path $root ".venv\Scripts\python.exe"
  $uiRoot = Join-Path $root "ui"
  if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment..."
    & py -3 -m venv .venv
  }

  if (-not (Test-Path $venvPython)) {
    throw "Failed to create virtual environment at $venvPython"
  }

  Write-Host "Installing dependencies..."
  & $venvPython -m pip install --upgrade pip
  & $venvPython -m pip install -r (Join-Path $root "requirements.txt")

  $npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
  if (-not $npmCmd) {
    throw "npm.cmd was not found. Install Node.js/npm on Windows first."
  }
  if (-not (Test-Path $uiRoot)) {
    throw "UI folder not found at $uiRoot"
  }

  Write-Host "Installing UI dependencies..."
  & $npmCmd install --prefix $uiRoot
  Write-Host "Building UI..."
  & $npmCmd run build --prefix $uiRoot

  if (-not (Test-Path $startMobileScript)) {
    throw "Missing start script at $startMobileScript"
  }

  $args = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $startMobileScript,
    "-OpenFirewall:$OpenFirewall",
    "-UiPort", "54312"
  )
  Write-Host "Starting Codrex app stack..."
  $startProc = Start-Process -FilePath "powershell.exe" -ArgumentList $args -WorkingDirectory $root -PassThru -Wait
  if ($startProc.ExitCode -ne 0) {
    throw "Codrex start script exited with code $($startProc.ExitCode)."
  }

  $resolvedPort = Read-ControllerPort -ConfigPath $configPath -FallbackPort $Port
  $appUrl = "http://127.0.0.1:$resolvedPort/"
  $summaryLines.Add("Setup complete.")
  $summaryLines.Add("App URL: $appUrl")
  if (Test-Path $launcherCmd) {
    Start-Process -FilePath $launcherCmd | Out-Null
    $summaryLines.Add("Launcher opened: $launcherCmd")
  }
  Start-Process $appUrl | Out-Null
  $summaryLines.Add("Browser opened: $appUrl")
} catch {
  $setupFailed = $true
  $summaryLines.Add("Setup failed.")
  $summaryLines.Add(($_.Exception.Message | Out-String).Trim())
  $summaryLines.Add("Controller logs: $env:LocalAppData\\Codrex\\remote-ui\\logs")
} finally {
  Write-Host ""
  Write-Host "Codrex Setup Summary"
  Write-Host "--------------------"
  foreach ($line in $summaryLines) {
    Write-Host $line
  }
  Write-Host ""
  if ($setupFailed) {
    Read-Host "Press Enter to close"
    exit 1
  }
  Read-Host "Press Enter to close"
}
