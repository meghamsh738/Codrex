$ErrorActionPreference = "Stop"
$taskNames = @(
  "CodrexRemoteController",
  "CodrexRemoteController.Startup",
  "CodrexRemoteController.Watchdog"
)

foreach ($taskName in $taskNames) {
  $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
  if (-not $task) {
    Write-Host "Task '$taskName' not found."
    continue
  }

  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
  Write-Host "Removed: $taskName"
}

Write-Host "Autostart cleanup complete."
