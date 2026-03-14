param(
  [int]$UiPort = 54312,
  [switch]$KeepController
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $PSCommandPath
$root = (Resolve-Path (Join-Path $scriptRoot "..\..")).Path
$diagnosticsScript = Join-Path $scriptRoot "codrex-diagnostics.ps1"
if (Test-Path $diagnosticsScript) {
  . $diagnosticsScript
}

function Read-SessionData {
  param([string]$Path)
  if (-not (Test-Path $Path)) { return $null }
  try {
    return (Get-Content -Path $Path -Raw | ConvertFrom-Json)
  } catch {}
  return $null
}

function Stop-UiProcessById {
  param([int]$ProcId)
  $p = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $ProcId) -ErrorAction SilentlyContinue
  if (-not $p) { return $false }
  try {
    Stop-Process -Id $ProcId -Force -ErrorAction Stop
    Write-Host "Stopped UI PID $ProcId."
    return $true
  } catch {
    Write-Host ("Failed to stop UI PID {0}: {1}" -f $ProcId, $_.Exception.Message)
  }
  return $false
}

function Stop-UiByPort {
  param([int]$Port)
  $stoppedAny = $false
  try {
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  } catch {
    $listeners = @()
  }
  if (-not $listeners) { return $false }

  foreach ($item in ($listeners | Select-Object -Unique OwningProcess)) {
    $procId = [int]$item.OwningProcess
    $proc = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $procId) -ErrorAction SilentlyContinue
    if (-not $proc) { continue }

    $looksLikeUi = $false
    if ($proc.CommandLine -and $proc.CommandLine -match "vite") { $looksLikeUi = $true }
    if ($proc.Name -match "node|npm") { $looksLikeUi = $true }

    if ($looksLikeUi) {
      try {
        Stop-Process -Id $procId -Force -ErrorAction Stop
        Write-Host "Stopped UI listener PID $procId on port $Port."
        $stoppedAny = $true
      } catch {
        Write-Host ("Failed to stop PID {0} on port {1}: {2}" -f $procId, $Port, $_.Exception.Message)
      }
    } else {
      Write-Host "Port $Port is owned by PID $procId ($($proc.Name)); not stopping automatically."
    }
  }
  return $stoppedAny
}

function Read-ControllerPort {
  param(
    [string]$ConfigPath,
    [string]$LocalConfigPath = "",
    [string]$LegacyLocalConfigPath = ""
  )
  foreach ($candidate in @($LocalConfigPath, $LegacyLocalConfigPath, $ConfigPath)) {
    if (-not $candidate -or -not (Test-Path $candidate)) { continue }
    try {
      $cfg = Get-Content -Path $candidate -Raw | ConvertFrom-Json
      if ($cfg -and $cfg.port) { return [int]$cfg.port }
    } catch {}
  }
  return 48787
}

function Test-PortListening {
  param([int]$Port)
  try {
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return [bool]$listeners
  } catch {}
  return $false
}

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

$runtimeDir = Get-CodrexRuntimeDir -RepoRoot $root
$stateDir = Join-Path $runtimeDir "state"
$sessionPath = Join-Path $stateDir "mobile.session.json"
$desktopPerfSnapshotPath = Join-Path $stateDir "desktop-perf.json"
$legacySessionPath = Join-Path (Join-Path $root "logs") "mobile.session.json"
$configPath = Join-Path $root "controller.config.json"
$localConfigPath = Join-Path $stateDir "controller.config.local.json"
$legacyLocalConfigPath = Join-Path $root "controller.config.local.json"
$logsDir = Join-Path $runtimeDir "logs"
$script:DiagnosticsLayout = Ensure-CodrexDiagnosticsLayout -RuntimeDir $runtimeDir
$script:DiagActionId = Get-CodrexCurrentActionId
if (-not $script:DiagActionId) {
  $script:DiagActionId = New-CodrexActionId
}
$script:DiagActionName = Get-CodrexCurrentActionName
if (-not $script:DiagActionName) {
  $script:DiagActionName = "stop"
}
$script:DiagSource = "stop-mobile"
$stopTimer = [System.Diagnostics.Stopwatch]::StartNew()

function Write-StopMobileDiagnostic {
  param(
    [bool]$Ok,
    [string]$Detail,
    [AllowNull()]
    [object]$Extra = $null
  )
  $currentSession = Read-SessionData -Path $sessionPath
  if (-not $currentSession -and (Test-Path $legacySessionPath)) {
    $currentSession = Read-SessionData -Path $legacySessionPath
  }
  $payload = [ordered]@{
    ok = $Ok
    status = if ($Ok) { "completed" } else { "error" }
    detail = $Detail
    repo_root = $root
    runtime_dir = $runtimeDir
    logs_dir = $logsDir
    controller_port = $controllerPort
    ui_port = $UiPort
    session_file = $sessionPath
    session_state_before = $script:DiagBeforeSessionState
    session_state_after = if ($currentSession) { "present" } else { "missing" }
    controller_port_snapshot_before = @($script:DiagBeforeControllerSnapshot)
    controller_port_snapshot_after = Get-CodrexPortDiagnosticsSnapshot -Ports @($controllerPort)
    ui_port_snapshot_before = @($script:DiagBeforeUiSnapshot)
    ui_port_snapshot_after = Get-CodrexPortDiagnosticsSnapshot -Ports @($UiPort)
    linked_process_logs = [ordered]@{
      controller_stdout = Join-Path $logsDir "controller.out.log"
      controller_stderr = Join-Path $logsDir "controller.err.log"
      ui_stdout = Join-Path $logsDir "ui.out.log"
      ui_stderr = Join-Path $logsDir "ui.err.log"
    }
  }
  if ($null -ne $Extra) {
    foreach ($property in $Extra.PSObject.Properties) {
      $payload[$property.Name] = $property.Value
    }
  }
  $null = Write-CodrexActionLog -RuntimeDir $runtimeDir -Action $script:DiagActionName -Source $script:DiagSource -Payload $payload -ActionId $script:DiagActionId -IsError:(-not $Ok)
  $null = Write-CodrexEventLog -RuntimeDir $runtimeDir -Source $script:DiagSource -Action $script:DiagActionName -ActionId $script:DiagActionId -Level $(if ($Ok) { "info" } else { "error" }) -Message $Detail -Context @{
    controller_port = $controllerPort
    ui_port = $UiPort
    session_state_after = if ($currentSession) { "present" } else { "missing" }
  }
}

trap {
  $message = if ($_.Exception -and $_.Exception.Message) { [string]$_.Exception.Message } else { [string]$_ }
  Write-StopMobileDiagnostic -Ok:$false -Detail $message -Extra ([pscustomobject]@{
    failure_stage = "stop-mobile"
  })
  exit 1
}

$session = Read-SessionData -Path $sessionPath
if (-not $session -and (Test-Path $legacySessionPath)) {
  $session = Read-SessionData -Path $legacySessionPath
}
$controllerPort = Read-ControllerPort -ConfigPath $configPath -LocalConfigPath $localConfigPath -LegacyLocalConfigPath $legacyLocalConfigPath
$controllerPid = $null

if ($session -and $session.controller_port) {
  $controllerPort = [int]$session.controller_port
}
if ($session -and $session.controller_pid) {
  $controllerPid = [int]$session.controller_pid
}
if ($session -and $session.ui_port) {
  $UiPort = [int]$session.ui_port
} elseif ($session -and $session.ui_mode -and [string]$session.ui_mode -ne "dev") {
  $UiPort = 0
}
$script:DiagBeforeSessionState = if ($session) { "present" } else { "missing" }
$script:DiagBeforeControllerSnapshot = Get-CodrexPortDiagnosticsSnapshot -Ports @($controllerPort)
$script:DiagBeforeUiSnapshot = Get-CodrexPortDiagnosticsSnapshot -Ports @($UiPort)
$null = Write-CodrexEventLog -RuntimeDir $runtimeDir -Source $script:DiagSource -Action $script:DiagActionName -ActionId $script:DiagActionId -Message "Stopping mobile stack script." -Context @{
  controller_port = $controllerPort
  ui_port = $UiPort
  keep_controller = [bool]$KeepController
  session_state_before = $script:DiagBeforeSessionState
}

function Disable-CodrexDesktopPerfMode {
  param([string]$SnapshotPath)
  if (-not (Test-Path $SnapshotPath)) {
    return $false
  }
  try {
    $perfWallpaperPath = Join-Path (Split-Path -Parent $SnapshotPath) "desktop-perf-wallpaper.bmp"
    $snapshotJson = Get-Content -Path $SnapshotPath -Raw -ErrorAction Stop
    if (-not $snapshotJson) {
      Remove-Item $SnapshotPath -Force -ErrorAction SilentlyContinue
      return $false
    }
    $snapshotB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($snapshotJson))
$restoreScriptTemplate = @'
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if (-not ('CodrexDesktopPerfNative' -as [type])) {
  Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class CodrexDesktopPerfNative {
  public const int SPI_SETDESKWALLPAPER = 20;
  public const int SPIF_UPDATEINIFILE = 0x01;
  public const int SPIF_SENDWININICHANGE = 0x02;
  public static readonly IntPtr HWND_BROADCAST = new IntPtr(0xffff);
  public const uint WM_SETTINGCHANGE = 0x001A;
  public const uint SMTO_ABORTIFHUNG = 0x0002;

  [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
  public static extern bool SystemParametersInfo(int uiAction, int uiParam, string pvParam, int fWinIni);

  [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
  public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, IntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out IntPtr lpdwResult);
}
"@
}

function Invoke-CodrexDesktopRefresh {
  param([string]$WallpaperPath)
  $resolvedWallpaper = ''
  if ($WallpaperPath) {
    try {
      $resolvedWallpaper = (Resolve-Path -LiteralPath $WallpaperPath -ErrorAction Stop).Path
    } catch {
      $resolvedWallpaper = $WallpaperPath
    }
  }
  [CodrexDesktopPerfNative]::SystemParametersInfo(
    [CodrexDesktopPerfNative]::SPI_SETDESKWALLPAPER,
    0,
    $resolvedWallpaper,
    [CodrexDesktopPerfNative]::SPIF_UPDATEINIFILE -bor [CodrexDesktopPerfNative]::SPIF_SENDWININICHANGE
  ) | Out-Null
  foreach ($area in @('Control Panel\Desktop', 'WindowsThemeElement', 'ImmersiveColorSet', 'TraySettings')) {
    $msgResult = [IntPtr]::Zero
    [CodrexDesktopPerfNative]::SendMessageTimeout(
      [CodrexDesktopPerfNative]::HWND_BROADCAST,
      [CodrexDesktopPerfNative]::WM_SETTINGCHANGE,
      [IntPtr]::Zero,
      $area,
      [CodrexDesktopPerfNative]::SMTO_ABORTIFHUNG,
      5000,
      [ref]$msgResult
    ) | Out-Null
  }
  & "$env:WINDIR\System32\cmd.exe" /c 'RUNDLL32.EXE user32.dll,UpdatePerUserSystemParameters 1, True' | Out-Null
}

$snapshotJson = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__SNAPSHOT_B64__'))
$snapshot = $snapshotJson | ConvertFrom-Json
$restoreWallpaper = [string]$snapshot.wallpaper
if ($snapshot.wallpaper_restore_path -and (Test-Path ([string]$snapshot.wallpaper_restore_path))) {
  $restoreWallpaper = [string]$snapshot.wallpaper_restore_path
}
Set-ItemProperty 'HKCU:\Control Panel\Desktop' -Name Wallpaper -Value $restoreWallpaper
Set-ItemProperty 'HKCU:\Control Panel\Desktop' -Name WallpaperStyle -Value ([string]$snapshot.wallpaper_style)
Set-ItemProperty 'HKCU:\Control Panel\Desktop' -Name TileWallpaper -Value ([string]$snapshot.tile_wallpaper)
if ($snapshot.background -ne $null) { try { Set-ItemProperty 'HKCU:\Control Panel\Colors' -Name Background -Value ([string]$snapshot.background) } catch {} }
if ($snapshot.min_animate -ne $null) { try { Set-ItemProperty 'HKCU:\Control Panel\Desktop\WindowMetrics' -Name MinAnimate -Value ([string]$snapshot.min_animate) } catch {} }
if ($snapshot.enable_transparency -ne $null -and [string]$snapshot.enable_transparency -ne '') { try { Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize' -Name EnableTransparency -Value ([int]$snapshot.enable_transparency) } catch {} }
Invoke-CodrexDesktopRefresh -WallpaperPath $restoreWallpaper
'@
    $restoreScript = $restoreScriptTemplate.Replace('__SNAPSHOT_B64__', $snapshotB64)
    $restoreScriptEncoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($restoreScript))
    & powershell.exe -NoProfile -EncodedCommand $restoreScriptEncoded | Out-Null
    Remove-Item $SnapshotPath -Force -ErrorAction SilentlyContinue
    Remove-Item $perfWallpaperPath -Force -ErrorAction SilentlyContinue
    return $true
  } catch {
    Write-Host ("Warning: desktop performance mode was not restored ({0})." -f $_.Exception.Message)
    return $false
  }
}

$uiStoppedBySession = $false
$uiStoppedByPort = $false
if ($UiPort -gt 0 -or ($session -and $session.ui_pid)) {
  if ($session -and $session.ui_pid) {
    $uiStoppedBySession = Stop-UiProcessById -ProcId ([int]$session.ui_pid)
  }
  if ($UiPort -gt 0) {
    $uiStoppedByPort = Stop-UiByPort -Port $UiPort
  }
  if (-not $uiStoppedBySession -and -not $uiStoppedByPort -and $UiPort -gt 0) {
    Write-Host "No mobile UI process stopped (port $UiPort)."
  }
}

if (-not $KeepController) {
  $stopControllerScript = Join-Path $scriptRoot "stop-controller.ps1"
  if (Test-Path $stopControllerScript) {
    $controllerArgs = @(
      "-NoProfile",
      "-ExecutionPolicy", "Bypass",
      "-File", $stopControllerScript,
      "-Port", [string]$controllerPort
    )
    if ($controllerPid) {
      $controllerArgs += @("-ProcId", [string]$controllerPid)
    }
    & powershell.exe @controllerArgs
  } else {
    Write-Host "Missing stop script at $stopControllerScript"
  }
}

if (Test-Path $sessionPath) {
  Remove-Item $sessionPath -Force -ErrorAction SilentlyContinue
}
if (Test-Path $legacySessionPath) {
  Remove-Item $legacySessionPath -Force -ErrorAction SilentlyContinue
}
$perfModeRestored = Disable-CodrexDesktopPerfMode -SnapshotPath $desktopPerfSnapshotPath

$controllerListening = Test-PortListening -Port $controllerPort
$uiListening = if ($UiPort -gt 0) { Test-PortListening -Port $UiPort } else { $false }
$result = [ordered]@{
  ok = (-not $controllerListening) -and (-not $uiListening)
  controller_port = $controllerPort
  controller_status = if ($controllerListening) { "controller_stop_failed" } elseif ($controllerPid) { "controller_stopped" } else { "controller_already_gone" }
  ui_port = $UiPort
  ui_stopped = (-not $uiListening)
  stale_session_file_removed = (-not (Test-Path $sessionPath)) -and (-not (Test-Path $legacySessionPath))
}
Write-StopMobileDiagnostic -Ok:([bool]$result.ok) -Detail $(if ($result.ok) { "Mobile stack stopped." } else { "Mobile stack stop did not complete cleanly." }) -Extra ([pscustomobject]@{
  controller_status = $result.controller_status
  ui_stopped = [bool]$result.ui_stopped
  stale_session_file_removed = [bool]$result.stale_session_file_removed
  perf_mode_restored = [bool]$perfModeRestored
  stop_complete_ms = [int]$stopTimer.ElapsedMilliseconds
})
$result | ConvertTo-Json -Compress | Write-Output
if (-not $result.ok) {
  exit 1
}
exit 0
