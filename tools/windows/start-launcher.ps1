param(
  [switch]$Tray
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $PSCommandPath
$repoRoot = (Resolve-Path (Join-Path $scriptRoot "..\..")).Path

function Get-CodrexRuntimeDir {
  param(
    [string]$RepoRoot
  )
  $override = [string]$env:CODEX_RUNTIME_DIR
  if ($override -and $override.Trim()) {
    return $override.Trim()
  }
  $localAppData = [string]$env:LocalAppData
  if ($localAppData -and $localAppData.Trim()) {
    return (Join-Path $localAppData "Codrex\remote-ui")
  }
  return (Join-Path $RepoRoot ".runtime")
}

function Write-StartupBreadcrumb {
  param(
    [string]$Message
  )
  try {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
    Add-Content -Path $startupLogPath -Value "$stamp [start-launcher] $Message"
  } catch {}
}

$launcherCurrentExe = Join-Path $repoRoot "launcher\Codrex.Launcher\bin\current\Codrex.Launcher.exe"
$launcherCurrentDll = Join-Path $repoRoot "launcher\Codrex.Launcher\bin\current\Codrex.Launcher.dll"
$launcherReleaseExe = Join-Path $repoRoot "launcher\Codrex.Launcher\bin\Release\net8.0-windows\Codrex.Launcher.exe"
$launcherPublishExe = Join-Path $repoRoot "launcher\Codrex.Launcher\bin\Release\net8.0-windows\win-x64\publish\Codrex.Launcher.exe"
$launcherDebugExe = Join-Path $repoRoot "launcher\Codrex.Launcher\bin\Debug\net8.0-windows\Codrex.Launcher.exe"
$legacyLauncher = Join-Path $repoRoot "tools\windows\mobile-launcher.ps1"
$hiddenPsWrapper = Join-Path $scriptRoot "powershell-hidden.vbs"
$runtimeDir = Get-CodrexRuntimeDir -RepoRoot $repoRoot
$logsDir = Join-Path $runtimeDir "logs"
if (-not (Test-Path $logsDir)) {
  New-Item -Path $logsDir -ItemType Directory -Force | Out-Null
}
$startupLogPath = Join-Path $logsDir "startup-bootstrap.log"

$trayArg = if ($Tray) { "--tray" } else { $null }
Write-StartupBreadcrumb ("invoked tray={0}" -f [bool]$Tray)

if (Test-Path $launcherCurrentExe) {
  $arguments = @()
  if ($trayArg) { $arguments += $trayArg }
  Write-StartupBreadcrumb ("launching current exe -> {0} {1}" -f $launcherCurrentExe, ($arguments -join ' '))
  if ($arguments.Count -gt 0) {
    Start-Process -FilePath $launcherCurrentExe -ArgumentList $arguments | Out-Null
  } else {
    Start-Process -FilePath $launcherCurrentExe | Out-Null
  }
  return
}

if (Test-Path $launcherCurrentDll) {
  $arguments = @($launcherCurrentDll)
  if ($trayArg) { $arguments += $trayArg }
  Write-StartupBreadcrumb ("launching current dll via dotnet -> {0} {1}" -f $launcherCurrentDll, ($arguments -join ' '))
  if ($arguments.Count -gt 0) {
    Start-Process -FilePath "dotnet" -ArgumentList $arguments | Out-Null
  } else {
    Start-Process -FilePath "dotnet" | Out-Null
  }
  return
}

foreach ($candidate in @($launcherReleaseExe, $launcherPublishExe, $launcherDebugExe)) {
  if (Test-Path $candidate) {
    $arguments = @()
    if ($trayArg) { $arguments += $trayArg }
    Write-StartupBreadcrumb ("launching fallback exe -> {0} {1}" -f $candidate, ($arguments -join ' '))
    if ($arguments.Count -gt 0) {
      Start-Process -FilePath $candidate -ArgumentList $arguments | Out-Null
    } else {
      Start-Process -FilePath $candidate | Out-Null
    }
    return
  }
}

Write-Warning "Codrex desktop launcher is not built yet. Falling back to the legacy PowerShell launcher."
Write-StartupBreadcrumb "launcher exe unavailable; falling back to legacy PowerShell launcher"
if (Test-Path $hiddenPsWrapper) {
  Start-Process -FilePath "wscript.exe" -ArgumentList @(
    $hiddenPsWrapper,
    "-STA",
    "-File", $legacyLauncher
  ) | Out-Null
} else {
  Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-STA",
    "-WindowStyle", "Hidden",
    "-File", $legacyLauncher
  ) -WindowStyle Hidden | Out-Null
}
