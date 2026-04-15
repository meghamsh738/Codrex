param(
  [switch]$ListOnly
)

$ErrorActionPreference = "Stop"

function Invoke-WslJson {
  param(
    [Parameter(Mandatory = $true)]
    [string[]]$Args
  )

  $quoted = $Args | ForEach-Object {
    "'" + ($_ -replace "'", "'\\''") + "'"
  }
  $command = "/mnt/d/codex-remote-ui/tools/wsl/codex-account.py " + ($quoted -join " ")
  $raw = & wsl.exe bash -lc $command
  if ($LASTEXITCODE -ne 0) {
    throw "WSL command failed: $command"
  }
  return ($raw -join "`n" | ConvertFrom-Json)
}

function Show-Accounts {
  $payload = Invoke-WslJson -Args @("list", "--json", "--with-usage")
  Write-Host ""
  Write-Host "Saved Codex accounts" -ForegroundColor Cyan
  Write-Host "Active account: $($payload.active_account_id)"
  Write-Host "Real codex path: $($payload.real_codex_path)"
  Write-Host ""
  $i = 1
  foreach ($account in $payload.accounts) {
    $marker = if ($account.active) { "*" } else { " " }
    $usageText = ""
    if ($account.usage -and $account.usage.ok) {
      $usageText = " [" + $account.usage.context_left + ", weekly " + $account.usage.weekly_left + "]"
    }
    Write-Host ("[{0}] {1} {2} -> {3}{4}" -f $i, $marker, $account.label, $account.codex_home, $usageText)
    $i += 1
  }
  return $payload
}

$payload = Show-Accounts

if ($ListOnly) {
  exit 0
}

$selection = Read-Host "Select account number to activate (Enter to keep current)"
if ([string]::IsNullOrWhiteSpace($selection)) {
  Write-Host "No change made."
  exit 0
}

[int]$index = 0
if (-not [int]::TryParse($selection, [ref]$index) -or $index -lt 1 -or $index -gt $payload.accounts.Count) {
  Write-Error "Invalid selection: $selection"
  exit 1
}

$chosen = $payload.accounts[$index - 1]
$result = Invoke-WslJson -Args @("activate", $chosen.id, "--json")
Write-Host ""
Write-Host ("Active account is now {0} ({1})" -f $result.active_account_id, $result.label) -ForegroundColor Green
Write-Host ("CODEX_HOME = {0}" -f $result.codex_home)
if ($result.baseline_sync) {
  $changed = @($result.baseline_sync.changed_items)
  if ($changed.Count -gt 0) {
    Write-Host ("Baseline synced from primary: {0}" -f ($changed -join ", ")) -ForegroundColor Yellow
    if ($result.baseline_sync.backup_root) {
      Write-Host ("Backup saved at {0}" -f $result.baseline_sync.backup_root)
    }
  }
}
