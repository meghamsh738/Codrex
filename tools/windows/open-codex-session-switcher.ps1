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

$payload = Invoke-WslJson -Args @("session-list", "--json")

Write-Host ""
Write-Host "Saved Codex sessions" -ForegroundColor Cyan
Write-Host "Current active account: $($payload.active_account_id) ($($payload.active_account_label))"
Write-Host ""

if (-not $payload.sessions -or $payload.sessions.Count -eq 0) {
  Write-Host "No saved session mappings were found."
  exit 0
}

$i = 1
foreach ($session in $payload.sessions) {
  Write-Host ("[{0}] {1} -> {2} ({3})" -f $i, $session.name, $session.account_label, $session.account_id)
  $i += 1
}

if ($ListOnly) {
  exit 0
}

$selection = Read-Host "Select session number to activate its mapped account (Enter to keep current)"
if ([string]::IsNullOrWhiteSpace($selection)) {
  Write-Host "No change made."
  exit 0
}

[int]$index = 0
if (-not [int]::TryParse($selection, [ref]$index) -or $index -lt 1 -or $index -gt $payload.sessions.Count) {
  Write-Error "Invalid selection: $selection"
  exit 1
}

$chosen = $payload.sessions[$index - 1]
$result = Invoke-WslJson -Args @("session-activate", $chosen.name, "--json")
Write-Host ""
Write-Host ("Session {0} now points to active account {1} ({2})" -f $chosen.name, $result.active_account_id, $result.label) -ForegroundColor Green
if ($result.baseline_sync) {
  $changed = @($result.baseline_sync.changed_items)
  if ($changed.Count -gt 0) {
    Write-Host ("Baseline synced from primary: {0}" -f ($changed -join ", ")) -ForegroundColor Yellow
    if ($result.baseline_sync.backup_root) {
      Write-Host ("Backup saved at {0}" -f $result.baseline_sync.backup_root)
    }
  }
}
