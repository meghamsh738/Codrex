param()

$ErrorActionPreference = "Stop"

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

function Write-VerifyLog {
  param(
    [string]$Message
  )
  $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
  Add-Content -Path $verifyLogPath -Value "$stamp [startup-verify] $Message"
}

$scriptRoot = Split-Path -Parent $PSCommandPath
$repoRoot = (Resolve-Path (Join-Path $scriptRoot "..\..")).Path
$runtimeDir = Get-CodrexRuntimeDir -RepoRoot $repoRoot
$logsDir = Join-Path $runtimeDir "logs"
if (-not (Test-Path $logsDir)) {
  New-Item -Path $logsDir -ItemType Directory -Force | Out-Null
}

$verifyLogPath = Join-Path $logsDir "startup-verify.log"
$bootstrapLogPath = Join-Path $logsDir "startup-bootstrap.log"
$taskName = "CodrexStartupVerify.NextLogon"

Start-Sleep -Seconds 20

Write-VerifyLog "begin"

try {
  $tasks = Get-ScheduledTask -TaskName @(
    "CodrexRemoteController.Startup",
    "CodrexRemoteController.Watchdog",
    "CodrexLauncher.Tray"
  ) -ErrorAction SilentlyContinue | Select-Object TaskName, State
  foreach ($task in $tasks) {
    Write-VerifyLog ("task {0} state={1}" -f $task.TaskName, $task.State)
  }
} catch {
  Write-VerifyLog ("task query failed: {0}" -f $_.Exception.Message)
}

try {
  $processMap = @{}
  Get-CimInstance Win32_Process | ForEach-Object { $processMap[[int]$_.ProcessId] = $_ }
  $interesting = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessName -in @("powershell", "pwsh", "conhost", "wscript", "cscript", "Codrex.Launcher")
  } | Sort-Object ProcessName, Id
  foreach ($proc in $interesting) {
    $cim = $processMap[[int]$proc.Id]
    $parent = if ($cim) { [string]$cim.ParentProcessId } else { "" }
    $cmd = if ($cim) { [string]$cim.CommandLine } else { "" }
    Write-VerifyLog ("proc {0} id={1} parent={2} hwnd={3} title={4} cmd={5}" -f $proc.ProcessName, $proc.Id, $parent, $proc.MainWindowHandle, $proc.MainWindowTitle, $cmd)
  }
} catch {
  Write-VerifyLog ("process query failed: {0}" -f $_.Exception.Message)
}

try {
  if (Test-Path $bootstrapLogPath) {
    Write-VerifyLog "bootstrap-tail-begin"
    Get-Content $bootstrapLogPath -Tail 40 | ForEach-Object { Add-Content -Path $verifyLogPath -Value $_ }
    Write-VerifyLog "bootstrap-tail-end"
  } else {
    Write-VerifyLog "bootstrap log missing"
  }
} catch {
  Write-VerifyLog ("bootstrap tail failed: {0}" -f $_.Exception.Message)
}

Write-VerifyLog "end"

try {
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
} catch {
}
