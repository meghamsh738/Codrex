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

$runtimeScript = Join-Path $root "tools\windows\codrex-runtime.ps1"
$buildLauncherScript = Join-Path $root "tools\windows\build-launcher.ps1"
$launcherCmd = Join-Path $root "Codrex.cmd"
$logsPath = Join-Path $env:LocalAppData "Codrex\\remote-ui\\logs"
$summaryLines = New-Object System.Collections.Generic.List[string]
$setupFailed = $false

function Build-DesktopLauncher {
  if (-not (Test-Path $buildLauncherScript)) {
    return [pscustomobject]@{
      built = $false
      detail = "Launcher build script not found yet."
    }
  }
  Write-Host "Building desktop launcher..."
  $launcherBuildOutput = @(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $buildLauncherScript 2>&1 | ForEach-Object { [string]$_ })
  $launcherBuildExit = if ($LASTEXITCODE -is [int]) { [int]$LASTEXITCODE } else { 0 }
  if ($launcherBuildExit -ne 0) {
    return [pscustomobject]@{
      built = $false
      detail = (($launcherBuildOutput -join "`n").Trim())
    }
  }
  $launcherExe = (($launcherBuildOutput | Select-Object -Last 1) -as [string]).Trim()

  return [pscustomobject]@{
    built = $true
    detail = if ($launcherExe) { "Desktop launcher built: $launcherExe" } else { "Desktop launcher built successfully." }
  }
}

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

  $launcherBuild = Build-DesktopLauncher
  $summaryLines.Add($launcherBuild.detail)

  if (-not (Test-Path $runtimeScript)) {
    throw "Missing runtime script at $runtimeScript"
  }

  $args = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $runtimeScript,
    "-Action", "start",
    "-UiPort", "54312"
  )
  if ($OpenFirewall) {
    $args += "-OpenFirewall"
  }
  Write-Host "Starting Codrex app stack..."
  $runtimeOutput = @(& powershell.exe @args 2>&1 | ForEach-Object { [string]$_ })
  $startExitCode = if ($LASTEXITCODE -is [int]) { [int]$LASTEXITCODE } else { 0 }
  $runtimeJson = ($runtimeOutput | Select-Object -Last 1)
  $startPayload = $null
  if ($runtimeJson) {
    try {
      $startPayload = $runtimeJson | ConvertFrom-Json
    } catch {}
  }
  if ($startExitCode -ne 0) {
    $detail = if ($startPayload -and $startPayload.detail) { [string]$startPayload.detail } else { ($runtimeOutput -join "`n").Trim() }
    throw "Codrex start failed. $detail"
  }

  if (-not $startPayload -or -not $startPayload.ok) {
    throw "Codrex start returned an invalid runtime payload."
  }

  $resolvedPort = if ($startPayload.controller_port) { [int]$startPayload.controller_port } else { $Port }
  $appUrl = if ($startPayload.local_url) { [string]$startPayload.local_url } else { "http://127.0.0.1:$resolvedPort/" }
  $summaryLines.Add("Setup complete.")
  $summaryLines.Add("App URL: $appUrl")
  if (Test-Path $launcherCmd) {
    Start-Process -FilePath $launcherCmd | Out-Null
    $summaryLines.Add("Launcher opened: $launcherCmd")
  }
  $summaryLines.Add("Browser not opened automatically. Use Open App from the launcher when you want the laptop UI.")
} catch {
  $setupFailed = $true
  $summaryLines.Add("Setup failed.")
  $summaryLines.Add(($_.Exception.Message | Out-String).Trim())
  $summaryLines.Add("Controller logs: $logsPath")
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
