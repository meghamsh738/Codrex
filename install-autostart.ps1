$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSCommandPath
$startScript = Join-Path $root "start-controller.ps1"
$watchdogScript = Join-Path $root "watchdog-controller.ps1"
$legacyTaskName = "CodrexRemoteController"
$startupTaskName = "CodrexRemoteController.Startup"
$watchdogTaskName = "CodrexRemoteController.Watchdog"

if (-not (Test-Path $startScript)) {
  throw "Missing start script at $startScript"
}
if (-not (Test-Path $watchdogScript)) {
  throw "Missing watchdog script at $watchdogScript"
}

$actionArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`""
$startupAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArgs
$startupTriggers = @(
  (New-ScheduledTaskTrigger -AtStartup),
  (New-ScheduledTaskTrigger -AtLogOn)
)
$startupSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

$watchdogArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$watchdogScript`""
$watchdogAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $watchdogArgs
$watchdogTrigger = New-ScheduledTaskTrigger `
  -Once -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes 1) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
$watchdogSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

$oldTask = Get-ScheduledTask -TaskName $legacyTaskName -ErrorAction SilentlyContinue
if ($oldTask) {
  try {
    Unregister-ScheduledTask -TaskName $legacyTaskName -Confirm:$false -ErrorAction Stop
  } catch {}
}

Register-ScheduledTask -TaskName $startupTaskName -Action $startupAction -Trigger $startupTriggers -Settings $startupSettings -Description "Start Codrex remote controller at startup/logon" -Force | Out-Null
Register-ScheduledTask -TaskName $watchdogTaskName -Action $watchdogAction -Trigger $watchdogTrigger -Settings $watchdogSettings -Description "Watchdog for Codrex remote controller (restart when unhealthy)" -Force | Out-Null

Write-Host "Autostart + watchdog installed."
Write-Host "Tasks:"
Write-Host " - $startupTaskName"
Write-Host " - $watchdogTaskName"
Write-Host "To remove: .\uninstall-autostart.ps1"
