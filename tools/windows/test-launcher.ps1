param(
  [string]$RepoRoot = "",
  [string]$ProgressFile = ""
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
  $RepoRoot = (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent)
}

if ($ProgressFile) {
  Add-Content -Path $ProgressFile -Value ("[{0}] Running runtime status smoke." -f (Get-Date -Format "HH:mm:ss")) -Encoding UTF8
}

$runtimeScript = Join-Path $RepoRoot "tools\windows\codrex-runtime.ps1"
$json = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runtimeScript -Action status
if ($LASTEXITCODE -ne 0) {
  throw "Runtime status command failed."
}

$payload = ($json -join "`n" | ConvertFrom-Json)
$launcherDll = Join-Path $RepoRoot "launcher\Codrex.Launcher\bin\current\Codrex.Launcher.dll"
$accountScript = Join-Path $RepoRoot "tools\wsl\codex-account.py"
$activeAccountId = ""
if (Test-Path -LiteralPath $accountScript) {
  try {
    $repoWsl = (& wsl.exe bash -lc ("wslpath -a '{0}'" -f ($RepoRoot -replace "\\", "/")) 2>$null | Select-Object -First 1).Trim()
    if ($repoWsl) {
      $accountJson = & wsl.exe bash -lc ("cd '{0}' && python3 tools/wsl/codex-account.py current --json" -f $repoWsl)
      if ($LASTEXITCODE -eq 0 -and $accountJson) {
        $accountPayload = ($accountJson -join "`n" | ConvertFrom-Json)
        $activeAccountId = [string]$accountPayload.active_account_id
      }
    }
  } catch {}
}

[ordered]@{
  ok = $true
  launcher_build_present = (Test-Path -LiteralPath $launcherDll)
  runtime_status = [string]$payload.status
  detail = [string]$payload.detail
  local_url = [string]$payload.local_url
  network_url = [string]$payload.network_url
  active_account_id = $activeAccountId
  runtime_dir = [string]$payload.runtime_dir
} | ConvertTo-Json -Compress -Depth 8
