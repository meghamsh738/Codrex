param(
  [int]$Port = 8787,
  [string]$Distro = "Ubuntu",
  [string]$Workdir = "/home/megha/codrex-work",
  [string]$FileRoot = "/home/megha/codrex-work",
  [switch]$OpenFirewall
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSCommandPath
Set-Location $root

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

$startScript = Join-Path $root "tools\windows\start-controller.ps1"
if (-not (Test-Path $startScript)) {
  throw "Missing start script at $startScript"
}

$args = @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", $startScript,
  "-Port", [string]$Port,
  "-Distro", $Distro,
  "-Workdir", $Workdir,
  "-FileRoot", $FileRoot
)
if ($OpenFirewall) {
  $args += "-OpenFirewall"
}

Write-Host "Starting Codrex controller..."
& powershell.exe @args
