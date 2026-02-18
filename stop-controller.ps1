param(
  [int]$Port = 8787
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSCommandPath
$configPath = Join-Path $root "controller.config.json"

if (Test-Path $configPath) {
  try {
    $loaded = Get-Content $configPath -Raw | ConvertFrom-Json
    if ($loaded -and $loaded.port) {
      $Port = [int]$loaded.port
    }
  } catch {}
}

$pattern = "--port\s+$Port\b"
$procs = Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and $_.CommandLine -match "app\.server:app" -and $_.CommandLine -match $pattern }

if (-not $procs) {
  Write-Host "No controller process found on port $Port."
  exit 0
}

foreach ($p in $procs) {
  try {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
    Write-Host "Stopped PID $($p.ProcessId)."
  } catch {
    Write-Host "Failed to stop PID $($p.ProcessId): $($_.Exception.Message)"
  }
}
