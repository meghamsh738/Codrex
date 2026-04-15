$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $PSCommandPath
$startScript = Join-Path $scriptRoot "start-controller.ps1"
$watchdogScript = Join-Path $scriptRoot "watchdog-controller.ps1"
$launcherScript = Join-Path $scriptRoot "start-launcher.ps1"
$hiddenPsWrapper = Join-Path $scriptRoot "powershell-hidden.vbs"
$repoRoot = (Resolve-Path (Join-Path $scriptRoot "..\..")).Path
$launcherCurrentExe = Join-Path $repoRoot "launcher\Codrex.Launcher\bin\current\Codrex.Launcher.exe"
$launcherCurrentDll = Join-Path $repoRoot "launcher\Codrex.Launcher\bin\current\Codrex.Launcher.dll"
$launcherReleaseExe = Join-Path $repoRoot "launcher\Codrex.Launcher\bin\Release\net8.0-windows\Codrex.Launcher.exe"
$launcherPublishExe = Join-Path $repoRoot "launcher\Codrex.Launcher\bin\Release\net8.0-windows\win-x64\publish\Codrex.Launcher.exe"
$launcherDebugExe = Join-Path $repoRoot "launcher\Codrex.Launcher\bin\Debug\net8.0-windows\Codrex.Launcher.exe"
$legacyTaskName = "CodrexRemoteController"
$startupTaskName = "CodrexRemoteController.Startup"
$watchdogTaskName = "CodrexRemoteController.Watchdog"
$launcherTaskName = "CodrexLauncher.Tray"

if (-not (Test-Path $startScript)) {
  throw "Missing start script at $startScript"
}
if (-not (Test-Path $watchdogScript)) {
  throw "Missing watchdog script at $watchdogScript"
}
if (-not (Test-Path $launcherScript)) {
  throw "Missing launcher start script at $launcherScript"
}
if (-not (Test-Path $hiddenPsWrapper)) {
  throw "Missing hidden PowerShell wrapper at $hiddenPsWrapper"
}

$startupArgs = "`"$hiddenPsWrapper`" -File `"$startScript`""
$startupAction = New-ScheduledTaskAction -Execute "wscript.exe" -Argument $startupArgs
$startupTriggers = @(
  (New-ScheduledTaskTrigger -AtStartup),
  (New-ScheduledTaskTrigger -AtLogOn)
)
$startupSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

$watchdogArgs = "`"$hiddenPsWrapper`" -File `"$watchdogScript`""
$watchdogAction = New-ScheduledTaskAction -Execute "wscript.exe" -Argument $watchdogArgs
$watchdogTrigger = New-ScheduledTaskTrigger `
  -Once -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes 1) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
$watchdogSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

$launcherAction = $null
if (Test-Path $launcherCurrentExe) {
  $launcherAction = New-ScheduledTaskAction -Execute $launcherCurrentExe -Argument "--tray" -WorkingDirectory (Split-Path -Parent $launcherCurrentExe)
} elseif (Test-Path $launcherCurrentDll) {
  $launcherAction = New-ScheduledTaskAction -Execute "dotnet" -Argument "`"$launcherCurrentDll`" --tray" -WorkingDirectory (Split-Path -Parent $launcherCurrentDll)
} else {
  foreach ($candidate in @($launcherReleaseExe, $launcherPublishExe, $launcherDebugExe)) {
    if (Test-Path $candidate) {
      $launcherAction = New-ScheduledTaskAction -Execute $candidate -Argument "--tray" -WorkingDirectory (Split-Path -Parent $candidate)
      break
    }
  }
}
if (-not $launcherAction) {
  $launcherArgs = "`"$hiddenPsWrapper`" -File `"$launcherScript`" -Tray"
  $launcherAction = New-ScheduledTaskAction -Execute "wscript.exe" -Argument $launcherArgs
}
$launcherTrigger = New-ScheduledTaskTrigger -AtLogOn
$launcherSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

$oldTask = Get-ScheduledTask -TaskName $legacyTaskName -ErrorAction SilentlyContinue
if ($oldTask) {
  try {
    Unregister-ScheduledTask -TaskName $legacyTaskName -Confirm:$false -ErrorAction Stop
  } catch {}
}

Register-ScheduledTask -TaskName $startupTaskName -Action $startupAction -Trigger $startupTriggers -Settings $startupSettings -Description "Start Codrex remote controller at startup/logon" -Force | Out-Null
Register-ScheduledTask -TaskName $watchdogTaskName -Action $watchdogAction -Trigger $watchdogTrigger -Settings $watchdogSettings -Description "Watchdog for Codrex remote controller (restart when unhealthy)" -Force | Out-Null
Register-ScheduledTask -TaskName $launcherTaskName -Action $launcherAction -Trigger $launcherTrigger -Settings $launcherSettings -Description "Start Codrex launcher hidden in the tray at logon" -Force | Out-Null

Write-Host "Autostart + watchdog installed."
Write-Host "Tasks:"
Write-Host " - $startupTaskName"
Write-Host " - $watchdogTaskName"
Write-Host " - $launcherTaskName"
Write-Host "To remove: .\uninstall-autostart.ps1"
