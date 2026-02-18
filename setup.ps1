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

$startScript = Join-Path $root "start-controller.ps1"
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
