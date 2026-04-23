param(
    [ValidateSet("windows", "tablet")]
    [string]$Target = "windows",
    [ValidateSet("launch-remote", "force-stop", "tap-node", "tap-text", "text-node", "tap-xy", "double-tap-xy", "right-click-xy", "long-press-xy", "swipe-xy", "screenshot", "capture-state", "dump-logcat", "run-scenario")]
    [string]$Action = "tap-xy",
    [ValidateSet("unlocked-basic", "unlocked-minimize-restore", "locked-basic", "locked-minimize-restore", "locked-unlock-recovery", "reconnect-after-host-restart")]
    [string]$Scenario = "",
    [int]$X = -1,
    [int]$Y = -1,
    [int]$X2 = -1,
    [int]$Y2 = -1,
    [int]$DurationMs = 450,
    [int]$WaitMs = 900,
    [string]$NodeId = "",
    [string]$TextValue = "",
    [string]$RunId = "",
    [string]$LedgerPath = "D:\coding projects\codrex android app\artifacts\privacy-lock-stabilization\BUG_LEDGER.md",
    [string]$Serial = "819f7ddd",
    [string]$Label = "screen-clicker",
    [string]$OutputDir = "D:\Codrex\remote-ui\logs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Ensure-OutputDir {
    if (-not (Test-Path $OutputDir)) {
        New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    }
}

function Ensure-CoordinatePair {
    if ($X -lt 0 -or $Y -lt 0) {
        throw "-X and -Y are required for $Action"
    }
}

function Ensure-SwipeCoordinates {
    if ($X -lt 0 -or $Y -lt 0 -or $X2 -lt 0 -or $Y2 -lt 0) {
        throw "-X, -Y, -X2, and -Y2 are required for $Action"
    }
}

function Invoke-TabletHarness {
    $harness = "D:\coding projects\codrex android app\artifacts\privacy-lock-stabilization\tablet-privacy-harness.ps1"
    if (-not (Test-Path $harness)) {
        throw "Tablet harness not found: $harness"
    }
    $args = @(
        "-Serial", $Serial,
        "-OutputDir", $OutputDir,
        "-Action", $Action,
        "-Label", $Label,
        "-WaitMs", "$WaitMs",
        "-DurationMs", "$DurationMs"
    )
    if ($NodeId) { $args += @("-NodeId", $NodeId) }
    if ($TextValue) { $args += @("-Text", $TextValue) }
    if ($Scenario) { $args += @("-Scenario", $Scenario) }
    if ($RunId) { $args += @("-RunId", $RunId) }
    if ($LedgerPath) { $args += @("-LedgerPath", $LedgerPath) }
    if ($X -ge 0) { $args += @("-X", "$X") }
    if ($Y -ge 0) { $args += @("-Y", "$Y") }
    if ($X2 -ge 0) { $args += @("-X2", "$X2") }
    if ($Y2 -ge 0) { $args += @("-Y2", "$Y2") }
    & powershell -ExecutionPolicy Bypass -File $harness @args
}

Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class CodrexScreenClickerNative {
    [DllImport("user32.dll", SetLastError=true)]
    public static extern bool SetCursorPos(int X, int Y);

    [DllImport("user32.dll", SetLastError=true)]
    public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);

    public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
    public const uint MOUSEEVENTF_LEFTUP = 0x0004;
    public const uint MOUSEEVENTF_RIGHTDOWN = 0x0008;
    public const uint MOUSEEVENTF_RIGHTUP = 0x0010;
}
"@

function Invoke-WindowsTap {
    param(
        [Parameter(Mandatory = $true)]
        [int]$TapX,
        [Parameter(Mandatory = $true)]
        [int]$TapY,
        [switch]$RightButton
    )
    [void][CodrexScreenClickerNative]::SetCursorPos($TapX, $TapY)
    Start-Sleep -Milliseconds 25
    if ($RightButton) {
        [CodrexScreenClickerNative]::mouse_event([CodrexScreenClickerNative]::MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, [UIntPtr]::Zero)
        [CodrexScreenClickerNative]::mouse_event([CodrexScreenClickerNative]::MOUSEEVENTF_RIGHTUP, 0, 0, 0, [UIntPtr]::Zero)
    } else {
        [CodrexScreenClickerNative]::mouse_event([CodrexScreenClickerNative]::MOUSEEVENTF_LEFTDOWN, 0, 0, 0, [UIntPtr]::Zero)
        [CodrexScreenClickerNative]::mouse_event([CodrexScreenClickerNative]::MOUSEEVENTF_LEFTUP, 0, 0, 0, [UIntPtr]::Zero)
    }
}

function Invoke-WindowsLongPress {
    param(
        [Parameter(Mandatory = $true)]
        [int]$PressX,
        [Parameter(Mandatory = $true)]
        [int]$PressY
    )
    [void][CodrexScreenClickerNative]::SetCursorPos($PressX, $PressY)
    Start-Sleep -Milliseconds 25
    [CodrexScreenClickerNative]::mouse_event([CodrexScreenClickerNative]::MOUSEEVENTF_LEFTDOWN, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds $DurationMs
    [CodrexScreenClickerNative]::mouse_event([CodrexScreenClickerNative]::MOUSEEVENTF_LEFTUP, 0, 0, 0, [UIntPtr]::Zero)
}

function Invoke-WindowsSwipe {
    Ensure-SwipeCoordinates
    $steps = [Math]::Max(4, [int]($DurationMs / 16))
    for ($i = 0; $i -le $steps; $i++) {
        $progress = [double]$i / [double]$steps
        $nextX = [int]([Math]::Round($X + (($X2 - $X) * $progress)))
        $nextY = [int]([Math]::Round($Y + (($Y2 - $Y) * $progress)))
        [void][CodrexScreenClickerNative]::SetCursorPos($nextX, $nextY)
        Start-Sleep -Milliseconds ([Math]::Max(1, [int]($DurationMs / ($steps + 1))))
    }
}

Ensure-OutputDir

if ($Target -eq "tablet") {
    Invoke-TabletHarness
    exit 0
}

switch ($Action) {
    "launch-remote" {
        Write-Output "launch-remote is tablet-only; use -Target tablet."
        exit 0
    }
    "force-stop" {
        Write-Output "force-stop is tablet-only; use -Target tablet."
        exit 0
    }
    "tap-node" {
        if (-not $NodeId.Trim()) {
            throw "-NodeId is required for tap-node"
        }
        Write-Output "tap-node is tablet-only; use -Target tablet."
        exit 0
    }
    "tap-text" {
        if (-not $TextValue.Trim()) {
            throw "-TextValue is required for tap-text"
        }
        Write-Output "tap-text is tablet-only; use -Target tablet."
        exit 0
    }
    "text-node" {
        if (-not $NodeId.Trim()) {
            throw "-NodeId is required for text-node"
        }
        Write-Output "text-node is tablet-only; use -Target tablet."
        exit 0
    }
    "tap-xy" {
        Ensure-CoordinatePair
        Invoke-WindowsTap -TapX $X -TapY $Y
    }
    "double-tap-xy" {
        Ensure-CoordinatePair
        Invoke-WindowsTap -TapX $X -TapY $Y
        Start-Sleep -Milliseconds 120
        Invoke-WindowsTap -TapX $X -TapY $Y
    }
    "right-click-xy" {
        Ensure-CoordinatePair
        Invoke-WindowsTap -TapX $X -TapY $Y -RightButton
    }
    "long-press-xy" {
        Ensure-CoordinatePair
        Invoke-WindowsLongPress -PressX $X -PressY $Y
    }
    "swipe-xy" {
        Invoke-WindowsSwipe
    }
    "capture-state" {
        Write-Output "capture-state is tablet-only; use -Target tablet."
        exit 0
    }
    "dump-logcat" {
        Write-Output "dump-logcat is tablet-only; use -Target tablet."
        exit 0
    }
    "run-scenario" {
        if (-not $Scenario.Trim()) {
            throw "-Scenario is required for run-scenario"
        }
        Write-Output "run-scenario is tablet-only; use -Target tablet."
        exit 0
    }
}

Start-Sleep -Milliseconds $WaitMs
[pscustomobject]@{
    Target = $Target
    Action = $Action
    X = $X
    Y = $Y
    X2 = $X2
    Y2 = $Y2
    DurationMs = $DurationMs
    WaitMs = $WaitMs
} | Format-List
